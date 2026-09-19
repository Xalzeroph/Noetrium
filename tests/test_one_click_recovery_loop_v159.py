from __future__ import annotations

from runtime_manager_test_support import make_runtime_control_store
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.launch_control import ExactRuntimeController, RuntimeAction, RuntimeControlError, RuntimeControlStore
from tests_support import frozen_runtime_manifest
from noetrium_platform.infrastructure.lifecycle.launch_control.one_click import OneClickRuntimeManager
from tests_support import recovery_lease_state
from noetrium_platform.infrastructure.reliability.recovery.execution.runtime.file_lock import FileLockedRecoveryExecutionFactory


def manifest():
    return frozen_runtime_manifest(qualified_deployment_digests=('d',), config_digests=(('c','h'),))

class FlakyAdapter:
    def __init__(self, fail_action, fail_times=1): self.fail_action=fail_action; self.remaining=fail_times; self.calls=[]
    def execute(self, action, manifest):
        self.calls.append(action)
        if action is self.fail_action and self.remaining:
            self.remaining-=1; raise RuntimeError('injected health failure')
        return (f'ref:{action.value}',)

class Plane:
    def __init__(self, controller): self.controller=controller
    def run_exact(self, manifest, *, control_id, action_guard=None, observer=None, observer_failure_sink=None):
        return self.controller.run(
            manifest,
            control_id=control_id,
            action_guard=action_guard,
            observer=observer,
            observer_failure_sink=observer_failure_sink,
        )

class OneClickRecoveryLoopTests(unittest.TestCase):
    def manager(self, root: Path, adapter, rounds=4):
        runtime_store=make_runtime_control_store(root/'runtime.json')
        controller=ExactRuntimeController(runtime_store,adapter)
        return OneClickRuntimeManager(
            Plane(controller),
            FileLockedRecoveryExecutionFactory(recovery_lease_state(root/'lease.json'), lock_path=root/'recovery.execution.lock'),
            runtime_store,
            max_recovery_rounds=rounds,
        )

    def test_services_ready_health_failure_recovers_from_service_reconcile_in_same_command(self):
        with TemporaryDirectory() as td:
            root=Path(td); adapter=FlakyAdapter(RuntimeAction.VERIFY_SERVICES_READY,1)
            report=self.manager(root,adapter).run_exact(manifest(),control_id='ctl',owner_id='owner')
            self.assertEqual(report.recovery_rounds,1)
            first_failure=adapter.calls.index(RuntimeAction.VERIFY_SERVICES_READY)
            self.assertEqual(adapter.calls[first_failure+1],RuntimeAction.RECONCILE_SERVICES)
            self.assertGreaterEqual(adapter.calls.count(RuntimeAction.START_EXACT_SERVICES),2)

    def test_identity_failure_is_not_auto_recovered(self):
        with TemporaryDirectory() as td:
            root=Path(td); adapter=FlakyAdapter(RuntimeAction.VERIFY_RELEASE,1)
            with self.assertRaises(RuntimeControlError) as cm:
                self.manager(root,adapter).run_exact(manifest(),control_id='ctl',owner_id='owner')
            self.assertFalse(cm.exception.recovery_required)
            self.assertEqual(adapter.calls,[RuntimeAction.VERIFY_RELEASE])

    def test_recovery_loop_is_bounded_for_persistent_uncertain_failure(self):
        with TemporaryDirectory() as td:
            root=Path(td); adapter=FlakyAdapter(RuntimeAction.START_EXACT_SERVICES,99)
            with self.assertRaises(RuntimeControlError):
                self.manager(root,adapter,rounds=2).run_exact(manifest(),control_id='ctl',owner_id='owner')
            self.assertEqual(adapter.calls.count(RuntimeAction.START_EXACT_SERVICES),3)

if __name__=='__main__': unittest.main()
