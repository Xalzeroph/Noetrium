from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceContractDrift, ServiceLaunchContract
import hashlib
import unittest

from noetrium_platform.infrastructure.lifecycle.launch_control import ExactRunProcessPort, RunLaunchIdentity, RunProcessBinding, RunProcessBindingError
from tests_support import context_action_runtime_bindings, frozen_runtime_manifest


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class SecretDriftRuntime:
    def reconcile_exact(self, contract): raise ServiceContractDrift("token=SECRET")
    def start_exact(self, contract): raise ServiceContractDrift("token=SECRET")
    def verify_ready_exact(self, contract): raise ServiceContractDrift("token=SECRET")


class RuntimeServiceErrorIsolationV180Tests(unittest.TestCase):
    def test_study_runtime_boundary_keeps_cause_but_does_not_copy_lower_text(self):
        manifest = frozen_runtime_manifest(
            release_digest=h("release"),
            prompt_generation_digest="pg",
            prompt_promotion_digest="pp",
            role_model_manifest_digest="roles",
            target_host_identity_digest=h("host"),
            participant_bindings=context_action_runtime_bindings(
                method_id="sem", method_abi="mabi", method_config=h("method"),
                environment_id="mc", environment_abi="eabi", environment_config=h("env"),
            ),
            experiment_spec_digest=h("study"),
        )
        identity = RunLaunchIdentity.from_manifest(manifest)
        exe = "/opt/rp/python"
        contract = ServiceLaunchContract(
            "study.main", identity.digest(), exe, (exe, "-m", "study"), "/srv/rp",
            h("env"), h("artifact"), h("runtime"), 10, 10, 1,
        )
        port = ExactRunProcessPort(RunProcessBinding(identity, contract, SecretDriftRuntime()))
        with self.assertRaises(RunProcessBindingError) as caught:
            port.reconcile(manifest)
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__, ServiceContractDrift)


if __name__ == "__main__": unittest.main()
