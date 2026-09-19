from __future__ import annotations

from runtime_manager_test_support import make_runtime_control_store
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.launch_control import ExactRuntimeController, RuntimeAction, RuntimeControlError, RuntimeControlStore, exact_runtime_plan
from tests_support import frozen_runtime_manifest


def manifest():
    return frozen_runtime_manifest(qualified_deployment_digests=('d1',), config_digests=(('c','h'),))

class Adapter:
    def __init__(self, fail=None): self.calls=[]; self.fail=fail
    def execute(self, action, manifest):
        self.calls.append(action)
        if action is self.fail: raise RuntimeError('health drift')
        return (f'ref:{action.value}',)

class RuntimeSuccessRevalidationTests(unittest.TestCase):
    def test_succeeded_state_reenters_full_exact_plan_instead_of_trusting_old_success(self):
        with TemporaryDirectory() as td:
            path=Path(td)/'runtime.json'
            first=Adapter(); ExactRuntimeController(make_runtime_control_store(path),first).run(manifest(),control_id='ctl')
            second=Adapter(); report=ExactRuntimeController(make_runtime_control_store(path),second).run(manifest(),control_id='ctl')
            expected=tuple(step.action for step in exact_runtime_plan().steps)
            self.assertEqual(tuple(second.calls),expected)
            self.assertEqual(report.executed_actions,expected)

    def test_revalidation_failure_is_visible_even_after_prior_success(self):
        with TemporaryDirectory() as td:
            path=Path(td)/'runtime.json'
            ExactRuntimeController(make_runtime_control_store(path),Adapter()).run(manifest(),control_id='ctl')
            second=Adapter(RuntimeAction.FINAL_STATUS)
            with self.assertRaises(RuntimeControlError) as cm:
                ExactRuntimeController(make_runtime_control_store(path),second).run(manifest(),control_id='ctl')
            self.assertEqual(cm.exception.action,RuntimeAction.FINAL_STATUS)
            self.assertTrue(cm.exception.recovery_required)
            third=Adapter()
            ExactRuntimeController(make_runtime_control_store(path),third).run(manifest(),control_id='ctl')
            self.assertEqual(third.calls[0],RuntimeAction.RECONCILE_SERVICES)

if __name__=='__main__': unittest.main()
