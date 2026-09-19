from runtime_manager_test_support import make_runtime_control_store
from pathlib import Path
import tempfile
import unittest

from noetrium_platform.infrastructure.lifecycle.launch_control import ExactRuntimeController, RuntimeAction, RuntimeControlError, RuntimeControlStore, RuntimeTxnPhase, exact_runtime_plan
from tests_support import frozen_runtime_manifest


def manifest(seed='seed'):
    return frozen_runtime_manifest(qualified_deployment_digests=('d1','d2'), config_digests=(('c','h'),), seed_identity=seed)

class Adapter:
    def __init__(self,fail=None): self.fail=fail; self.calls=[]
    def execute(self,action,m):
        self.calls.append(action)
        if action==self.fail: raise OSError('injected')
        return (f'evidence:{action.value}',)

class RuntimeManagerV25Tests(unittest.TestCase):
    def test_exact_plan_runs_in_order(self):
        with tempfile.TemporaryDirectory() as td:
            a=Adapter(); report=ExactRuntimeController(make_runtime_control_store(Path(td)/'state.json'),a).run(manifest(),control_id='ctl')
            self.assertEqual(tuple(a.calls),tuple(x.action for x in exact_runtime_plan().steps)); self.assertEqual(report.state.phase,RuntimeTxnPhase.SUCCEEDED)

    def test_mutating_failure_requires_reconcile_before_retry(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'state.json'; a=Adapter(RuntimeAction.START_EXACT_SERVICES); ctl=ExactRuntimeController(make_runtime_control_store(path),a)
            with self.assertRaises(RuntimeControlError) as cm: ctl.run(manifest(),control_id='ctl')
            self.assertTrue(cm.exception.recovery_required); self.assertEqual(make_runtime_control_store(path).read().phase,RuntimeTxnPhase.RECOVERY_REQUIRED)
            b=Adapter(); ctl2=ExactRuntimeController(make_runtime_control_store(path),b); ctl2.run(manifest(),control_id='ctl')
            self.assertEqual(b.calls[0],RuntimeAction.RECONCILE_SERVICES); self.assertEqual(b.calls.count(RuntimeAction.START_EXACT_SERVICES),1)

    def test_study_start_failure_rewinds_to_study_reconcile_not_model_restart(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'state.json'; a=Adapter(RuntimeAction.START_EXACT_RUN)
            with self.assertRaises(RuntimeControlError): ExactRuntimeController(make_runtime_control_store(path),a).run(manifest(),control_id='ctl')
            b=Adapter(); ExactRuntimeController(make_runtime_control_store(path),b).run(manifest(),control_id='ctl')
            self.assertEqual(b.calls[0],RuntimeAction.RECONCILE_RUN); self.assertNotIn(RuntimeAction.START_EXACT_SERVICES,b.calls)

    def test_nonrecoverable_nonmutating_failure_retries_same_verification(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'state.json'; a=Adapter(RuntimeAction.VERIFY_HOST_INVENTORY)
            with self.assertRaises(RuntimeControlError) as cm:
                ExactRuntimeController(make_runtime_control_store(path),a).run(manifest(),control_id='ctl')
            self.assertFalse(cm.exception.recovery_required)
            b=Adapter(); ExactRuntimeController(make_runtime_control_store(path),b).run(manifest(),control_id='ctl')
            self.assertEqual(b.calls[0],RuntimeAction.VERIFY_HOST_INVENTORY)

    def test_runtime_health_verification_failure_reconciles_services_before_retry(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'state.json'; a=Adapter(RuntimeAction.VERIFY_RUNTIME_QUALIFICATION)
            with self.assertRaises(RuntimeControlError) as cm:
                ExactRuntimeController(make_runtime_control_store(path),a).run(manifest(),control_id='ctl')
            self.assertTrue(cm.exception.recovery_required)
            b=Adapter(); ExactRuntimeController(make_runtime_control_store(path),b).run(manifest(),control_id='ctl')
            self.assertEqual(b.calls[0],RuntimeAction.RECONCILE_SERVICES)

    def test_runtime_failure_persists_only_redacted_descriptor(self):
        class SecretAdapter:
            def execute(self, action, manifest):
                if action is RuntimeAction.VERIFY_HOST_INVENTORY:
                    raise RuntimeError("api_key=super-secret-token password=hunter2")
                return ()

        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'state.json'
            with self.assertRaises(RuntimeControlError) as cm:
                ExactRuntimeController(make_runtime_control_store(path),SecretAdapter()).run(manifest(),control_id='ctl')
            state=make_runtime_control_store(path).read()
            self.assertEqual(state.last_error_type,'RuntimeError')
            self.assertIn('<REDACTED>',state.last_error)
            self.assertNotIn('super-secret-token',state.last_error)
            self.assertNotIn('hunter2',state.last_error)
            self.assertEqual(len(state.last_error_digest or ''),64)
            self.assertNotIn('super-secret-token',str(cm.exception))

    def test_manifest_drift_blocks_resume(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'state.json'; a=Adapter(RuntimeAction.VERIFY_HOST_INVENTORY)
            with self.assertRaises(RuntimeControlError): ExactRuntimeController(make_runtime_control_store(path),a).run(manifest(),control_id='ctl')
            with self.assertRaises(ValueError): ExactRuntimeController(make_runtime_control_store(path),Adapter()).run(manifest('other'),control_id='ctl')

if __name__=='__main__': unittest.main()
