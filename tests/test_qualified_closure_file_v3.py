from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import time

from noetrium_platform.capabilities.model.serving.api import (
    DeploymentPlacement,
    QualificationCertificate,
    QualifiedDeploymentManifest,
    ResourceEnvelope,
    RoleModelAssignment,
    RoleModelManifest,
    RuntimeCanaryEvidence,
    RuntimeQualificationReceipt,
    ServiceHeartbeat,
    build_runtime_qualification_receipt,
)
from noetrium_platform.capabilities.model.serving.composition import publish_qualified_model_deployment_closure
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointRoute,
    QualifiedModelClosurePublication,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    PersistedQualifiedModelEndpointBinding,
    load_qualified_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.providers import (
    DirectoryRuntimeCanaryEvidenceStore,
    DirectoryRuntimeQualificationEvidenceStore,
)
from noetrium_platform.capabilities.model.stack.api import ModelArtifactClosure, ModelStackSpec, RuntimeBuildIdentity
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity, canonical_digest


def _digest(seed: str) -> str:
    return (seed * 64)[:64]


class QualifiedClosureFileTests(unittest.TestCase):
    def test_file_reader_reconstructs_and_binds_one_qualified_role(self) -> None:
        identity = ImmutableModelIdentity(
            "planner-model",
            "model-v1",
            "revision-v1",
            "vllm",
            "0.1",
            "bf16",
            None,
            8192,
        )
        stack = ModelStackSpec(
            identity,
            ModelArtifactClosure(_digest("a"), _digest("b"), _digest("c")),
            RuntimeBuildIdentity(
                _digest("d"), _digest("e"), _digest("f"), "cuda", "nccl", "torch", _digest("a")
            ),
            1,
            1,
            1,
            1,
            None,
            None,
            None,
            None,
            "fcfs",
        )
        certificate = QualificationCertificate(
            stack.digest(),
            _digest("f"),
            ("planner",),
            ResourceEnvelope(1, 1, 1, 1.0, 1.0, 1.0),
            _digest("b"),
        )
        deployment = QualifiedDeploymentManifest(
            "deployment-1",
            stack,
            certificate,
            DeploymentPlacement(("GPU-1",)),
            _digest("b"),
        )
        route = ModelEndpointRoute(
            deployment.deployment_id,
            deployment.digest(),
            "http://127.0.0.1:30000",
            timeout_s=17.0,
        )
        roles = RoleModelManifest((RoleModelAssignment("planner", deployment.deployment_id),))
        runtime_manifest_digest = _digest("c")

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            now = time.time()
            heartbeat = ServiceHeartbeat(
                deployment.deployment_id, stack.digest(), 123, "start-123", _digest("7"),
                True, certificate.digest(), now - 0.1,
            )
            heartbeat_ref = (
                f"heartbeat:{heartbeat.deployment_id}:{heartbeat.pid}:"
                f"{heartbeat.process_start_marker}:{heartbeat.timestamp}"
            )
            receipt = build_runtime_qualification_receipt(
                deployment, heartbeat, required_roles=("planner",),
                evidence_refs=(heartbeat_ref,), max_heartbeat_age_seconds=60.0, now=now,
            )
            canary = RuntimeCanaryEvidence(
                deployment_id=deployment.deployment_id,
                deployment_generation=deployment.digest(),
                route_digest=canonical_digest(route),
                role="planner",
                canary_id="planner-json",
                suite_digest=_digest("8"),
                process_pid=receipt.process_pid,
                process_start_marker=receipt.process_start_marker,
                argv_digest=receipt.argv_digest,
                request_digest=_digest("9"),
        probe_digest=_digest("0"),
                response_digest=_digest("a"),
                contract_digest=_digest("b"),
                passed=True,
                observed_at=now,
            )
            receipt = replace(
                receipt,
                evidence_refs=(*receipt.evidence_refs, f"canary:sha256:{canary.evidence_digest}"),
            )
            closure_path = root / "closure.json"
            publish_qualified_model_deployment_closure(
                closure_path,
                QualifiedModelClosurePublication(
                    role_manifest=roles,
                    deployments=(deployment,),
                    routes=(route,),
                    runtime_manifest_digest=runtime_manifest_digest,
                    runtime_qualification_receipts=(receipt,),
                    runtime_canary_evidence=(canary,),
                ),
            )

            closure = load_qualified_model_deployment_closure(
                closure_path,
                runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
                runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
            )
            binding = PersistedQualifiedModelEndpointBinding(closure).binding_for(
                role="planner",
                prompt_generation="prompt-generation-v1",
            )

        self.assertEqual(binding.deployment_id, "deployment-1")
        self.assertEqual(binding.model, identity)
        self.assertEqual(binding.timeout_s, 17.0)
        self.assertEqual(binding.max_admitted_concurrency, 1)


if __name__ == "__main__":
    unittest.main()
