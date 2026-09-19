from dataclasses import dataclass
import unittest

from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodRuntimeIdentity
from noetrium_platform.capabilities.participant.method.runtime import MethodRuntimeEndpoint
from tests_support import context_action_runtime_bindings, frozen_runtime_manifest, run_launch_manifest


@dataclass(frozen=True)
class _Implementation:
    identity: MethodIdentity


class _RuntimeA:
    runtime_identity = MethodRuntimeIdentity("runtime.a", "1", "abi1", "a" * 64)

    def open_session(self, implementation, *, binding, session_id, services):
        raise AssertionError("not used")


class _RuntimeB:
    runtime_identity = MethodRuntimeIdentity("runtime.b", "1", "abi1", "b" * 64)

    def open_session(self, implementation, *, binding, session_id, services):
        raise AssertionError("not used")


class MethodConfigurationIdentityV106Tests(unittest.TestCase):
    def test_endpoint_keeps_implementation_identity_separate_from_runtime_binding(self):
        implementation = _Implementation(MethodIdentity("method-a", "1", "abi1", "schema1", "c" * 64))
        a = MethodRuntimeEndpoint(implementation, _RuntimeA())
        b = MethodRuntimeEndpoint(implementation, _RuntimeB())
        self.assertEqual(a.identity, b.identity)
        self.assertNotEqual(a.runtime_identity, b.runtime_identity)
        self.assertNotEqual(a.binding_digest, b.binding_digest)

    def test_run_launch_manifest_changes_when_runtime_binding_configuration_changes(self):
        a = run_launch_manifest(
            participant_bindings=context_action_runtime_bindings(method_id="method-a", method_config="A")
        )
        b = run_launch_manifest(
            participant_bindings=context_action_runtime_bindings(method_id="method-a", method_config="B")
        )
        self.assertEqual(
            a.participant_implementation_inventory_digest,
            b.participant_implementation_inventory_digest,
        )
        self.assertNotEqual(a.participant_binding_manifest_digest, b.participant_binding_manifest_digest)
        self.assertNotEqual(a.digest(), b.digest())

    def test_frozen_runtime_manifest_changes_when_runtime_binding_configuration_changes(self):
        a = frozen_runtime_manifest(
            participant_bindings=context_action_runtime_bindings(method_id="method-a", method_config="A")
        )
        b = frozen_runtime_manifest(
            participant_bindings=context_action_runtime_bindings(method_id="method-a", method_config="B")
        )
        self.assertEqual(
            a.participant_implementation_inventory_digest,
            b.participant_implementation_inventory_digest,
        )
        self.assertNotEqual(a.participant_binding_manifest_digest, b.participant_binding_manifest_digest)
        self.assertNotEqual(a.digest(), b.digest())


if __name__ == "__main__":
    unittest.main()
