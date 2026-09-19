from __future__ import annotations

from prompt_os_test_support import make_prompt_registry
from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest

from noetrium_platform.capabilities.participant.core.api.contracts import ParticipantImplementationIdentity
from noetrium_platform.capabilities.participant.core.api.frozen_manifests import ParticipantImplementationInventory, ParticipantRuntimeBindingManifest, ParticipantRuntimeInventory
from noetrium_platform.capabilities.model.request.prompt.runtime import DurablePromptRegistry, PromptPromotionEvidence
from noetrium_platform.capabilities.model.request.prompt.runtime import default_block_policies, default_output_schemas, default_prompt_specs
from noetrium_platform.capabilities.model.request.prompt.runtime.qualification import PromptQualification
from noetrium_platform.foundation.governance.release.runtime.manifest import build_release_manifest
from noetrium_platform.foundation.governance.release.runtime.verification import SourceTreeReleaseEvidenceReader
from noetrium_platform.infrastructure.lifecycle.launch_control import (
    ActivePromptPromotionVerifier,
    FrozenParticipantBindingVerificationPort,
    FrozenParticipantImplementationVerificationPort,
    FrozenParticipantRuntimeVerificationPort,
    FrozenReleaseVerifier,
)
from tests_support import context_action_runtime_bindings, frozen_runtime_manifest


def h(v): return hashlib.sha256(v.encode()).hexdigest()


def frozen(**overrides):
    base=dict(
        release_digest="release",
        prompt_generation_digest="pg",
        prompt_promotion_digest="pp",
        role_model_manifest_digest="roles",
        qualified_deployment_digests=(),
        target_host_identity_digest=h("host"),
        participant_bindings=context_action_runtime_bindings(
            method_id="sem", method_version="1", method_abi="mabi", method_schema="schema", method_config="method-config",
            environment_id="mc", environment_version="2", environment_abi="eabi", environment_schema="schema", environment_config="env-config",
        ),
        experiment_spec_digest="study",
        config_digests=(),
        seed_identity="seed",
    )
    base.update(overrides)
    return frozen_runtime_manifest(**base)


class RuntimeVerificationPortsV114Tests(unittest.TestCase):
    def test_release_port_detects_file_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"pyproject.toml").write_text('[project]\nname="x"\nversion="1.2.3"\nrequires-python=">=3.12"\n')
            (root/"a.txt").write_text("a")
            release=build_release_manifest(root)
            port=FrozenReleaseVerifier(SourceTreeReleaseEvidenceReader(root, release))
            refs=port.verify(frozen(release_digest=release.digest()))
            self.assertIn(f"source-tree:{release.source_tree_sha256}",refs)
            (root/"a.txt").write_text("changed")
            with self.assertRaisesRegex(RuntimeError,"release artifact verification failed"):
                port.verify(frozen(release_digest=release.digest()))

    def test_implementation_and_runtime_binding_are_verified_by_distinct_ports(self):
        bindings=context_action_runtime_bindings(
            method_id="sem", method_version="1", method_abi="mabi", method_schema="schema", method_config="method-config",
            environment_id="mc", environment_version="2", environment_abi="eabi", environment_schema="schema", environment_config="env-config",
        )
        inventory=ParticipantImplementationInventory.from_bindings(bindings)
        runtime_inventory=ParticipantRuntimeInventory.from_bindings(bindings)
        binding_manifest=ParticipantRuntimeBindingManifest.build(bindings, inventory, runtime_inventory)
        manifest=frozen()
        impl_port=FrozenParticipantImplementationVerificationPort(inventory)
        runtime_port=FrozenParticipantRuntimeVerificationPort(runtime_inventory)
        binding_port=FrozenParticipantBindingVerificationPort(binding_manifest)
        self.assertEqual(len(impl_port.verify(manifest)),3)
        self.assertGreaterEqual(len(runtime_port.verify(manifest)),2)
        self.assertEqual(len(binding_port.verify(manifest)),3)

        changed_impl=ParticipantImplementationIdentity("method","sem","9","mabi","schema","e" * 64)
        changed_binding=replace(bindings[0], implementation=changed_impl)
        changed_inventory=ParticipantImplementationInventory.from_bindings((changed_binding, bindings[1]))
        with self.assertRaises(ValueError):
            impl_port.verify(replace(manifest, participant_implementation_inventory_digest=changed_inventory.digest()))

        config_drift=replace(bindings[0], configuration_digest="other-config")
        drift_manifest=ParticipantRuntimeBindingManifest.build((config_drift, bindings[1]), inventory, runtime_inventory)
        # same implementation inventory, different runtime binding
        impl_port.verify(manifest)
        with self.assertRaises(ValueError):
            binding_port.verify(replace(manifest, participant_binding_manifest_digest=drift_manifest.digest()))

        changed_runtime = replace(bindings[0].runtime, runtime_version="9", artifact_digest=h("runtime-drift"))
        changed_runtime_binding = replace(bindings[0], runtime=changed_runtime)
        changed_runtime_inventory = ParticipantRuntimeInventory.from_bindings((changed_runtime_binding, bindings[1]))
        with self.assertRaises(ValueError):
            runtime_port.verify(replace(manifest, participant_runtime_inventory_digest=changed_runtime_inventory.digest()))

    def test_prompt_port_binds_active_payload_and_promotion_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); registry=make_prompt_registry(root)
            generation=registry.stage("g1",default_prompt_specs(),default_block_policies(),default_output_schemas())
            _manifest,bundles=registry.generation_store.load("g1")
            resume=("model","repo","rev","engine","1","dtype",None,4096)
            quals=tuple(PromptQualification("suite",bundle.digest,bundle.role,resume,1,1,1,1,True) for bundle in bundles)
            evidence=PromptPromotionEvidence("g1",generation.payload_sha256,"suite",quals,resume,h("objective"),1.0)
            record=registry.promote(evidence)
            m=frozen(prompt_generation_digest=generation.payload_sha256,prompt_promotion_digest=record.promotion_evidence_digest)
            refs=ActivePromptPromotionVerifier(registry.promotion_store).verify(m)
            self.assertIn("prompt-active:g1",refs)
            with self.assertRaises(ValueError):
                ActivePromptPromotionVerifier(registry.promotion_store).verify(replace(m,prompt_promotion_digest=h("wrong")))


if __name__ == "__main__": unittest.main()
