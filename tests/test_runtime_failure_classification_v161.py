from __future__ import annotations

from runtime_manager_test_support import make_runtime_control_store
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.reliability.primitives.runtime_faults import FrozenRuntimeIdentityViolation, RuntimeOperationalHealthUnavailable
from noetrium_platform.infrastructure.lifecycle.launch_control import ExactRuntimeController, RuntimeAction, RuntimeControlError, RuntimeControlStore
from tests_support import frozen_runtime_manifest


def manifest():
    return frozen_runtime_manifest(qualified_deployment_digests=('d',), config_digests=(('c','h'),))


class Adapter:
    def __init__(self, action, error): self.action=action; self.error=error; self.calls=[]
    def execute(self, action, manifest):
        self.calls.append(action)
        if action is self.action: raise self.error
        return ()


class RuntimeFailureClassificationV161Tests(unittest.TestCase):
    def test_identity_violation_overrides_mutating_step_default_and_fails_closed(self):
        with TemporaryDirectory() as td:
            adapter=Adapter(RuntimeAction.START_EXACT_SERVICES,FrozenRuntimeIdentityViolation('contract drift'))
            with self.assertRaises(RuntimeControlError) as cm:
                ExactRuntimeController(make_runtime_control_store(Path(td)/'runtime.json'),adapter).run(manifest(),control_id='ctl')
            self.assertFalse(cm.exception.recovery_required)

    def test_operational_health_failure_uses_step_reconcile_policy(self):
        with TemporaryDirectory() as td:
            adapter=Adapter(RuntimeAction.VERIFY_RUNTIME_QUALIFICATION,RuntimeOperationalHealthUnavailable('heartbeat stale'))
            with self.assertRaises(RuntimeControlError) as cm:
                ExactRuntimeController(make_runtime_control_store(Path(td)/'runtime.json'),adapter).run(manifest(),control_id='ctl')
            self.assertTrue(cm.exception.recovery_required)

    def test_identity_violation_on_health_step_does_not_restart_services(self):
        with TemporaryDirectory() as td:
            adapter=Adapter(RuntimeAction.VERIFY_RUNTIME_QUALIFICATION,FrozenRuntimeIdentityViolation('qualification digest drift'))
            with self.assertRaises(RuntimeControlError) as cm:
                ExactRuntimeController(make_runtime_control_store(Path(td)/'runtime.json'),adapter).run(manifest(),control_id='ctl')
            self.assertFalse(cm.exception.recovery_required)

if __name__=='__main__': unittest.main()
