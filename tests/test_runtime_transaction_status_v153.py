from __future__ import annotations

from runtime_manager_test_support import make_runtime_control_store
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.forensics.runtime.diagnostic_adapter import ForensicDiagnosticEvidence
from noetrium_platform.evidence.observability.status.runtime import PlatformStatusService
from noetrium_platform.infrastructure.reliability.diagnostics.runtime.status_projection import ForensicStatusProbe
from noetrium_platform.infrastructure.lifecycle.launch_control import RuntimeControlStore, RuntimeTxnPhase
from tests_support import recovery_lease_state
from noetrium_platform.infrastructure.reliability.recovery.composition import compose_recovery_lease_status_probe
from noetrium_platform.infrastructure.lifecycle.launch_control.status_readers import RuntimeControlStatusReader
from noetrium_platform.infrastructure.lifecycle.launch_control.runtime_transaction_status import RuntimeTransactionStatusProbe


class RuntimeTransactionStatusTests(unittest.TestCase):
    def status(self, root: Path, runtime: RuntimeControlStore):
        store=ForensicStore(root/'forensics')
        service=PlatformStatusService((
            RuntimeTransactionStatusProbe(RuntimeControlStatusReader(runtime.state_store, runtime.history)),
            compose_recovery_lease_status_probe(recovery_lease_state(root/'lease')),
            ForensicStatusProbe(ForensicDiagnosticEvidence(store)),
        ))
        return service,store

    def test_running_mutating_action_is_operationally_degraded_not_ready(self):
        with TemporaryDirectory() as td:
            root=Path(td); runtime=make_runtime_control_store(root/'runtime.json')
            state=runtime.create('ctl','manifest')
            runtime.write(replace(state,phase=RuntimeTxnPhase.RUNNING,current_action='start_exact_services',current_mutating=True))
            service,store=self.status(root,runtime)
            try:
                data=service.snapshot().to_dict(); rt=next(x for x in data['subsystems'] if x['subsystem']=='runtime')
                self.assertEqual(rt['state'],'degraded_operational')
                self.assertIn('current=start_exact_services',rt['summary'])
                self.assertIn('reconcile anchor',' '.join(rt['next_commands']))
                self.assertEqual(rt['reason_codes'],['runtime_transaction_in_progress'])
            finally: store.close()

    def test_history_tail_lag_is_degraded_evidence_without_status_mutation(self):
        with TemporaryDirectory() as td:
            root=Path(td); runtime=make_runtime_control_store(root/'runtime.json')
            state=runtime.create('ctl','manifest')
            # Simulate crash window: authoritative file advanced, history did not.\n
            advanced=replace(state,phase=RuntimeTxnPhase.SUCCEEDED,completed_actions=('x',))
            from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
            from noetrium_platform.infrastructure.lifecycle.launch_control.runtime_state_codec import RuntimeControlStateCodec
            state_path = root / 'runtime.json'
            history_path = root / 'runtime.json.history.jsonl'
            atomic_replace_bytes(state_path, RuntimeControlStateCodec().encode(advanced))
            before=history_path.read_bytes()
            service,store=self.status(root,runtime)
            try:
                data=service.snapshot().to_dict(); rt=next(x for x in data['subsystems'] if x['subsystem']=='runtime')
                self.assertEqual(rt['state'],'degraded_evidence')
                self.assertIn('history_tail=',rt['summary'])
                self.assertEqual(history_path.read_bytes(),before)
                self.assertEqual(rt['reason_codes'],['runtime_history_tail_mismatch'])
            finally: store.close()


    def test_history_tail_exception_is_redacted_and_identified(self):
        with TemporaryDirectory() as td:
            root=Path(td); runtime=make_runtime_control_store(root/'runtime.json')
            runtime.create('ctl','manifest')
            service,store=self.status(root,runtime)
            secret='status-secret-value'
            try:
                with patch.object(
                    runtime.history,
                    'assert_tail_matches',
                    side_effect=RuntimeError(f'token={secret}'),
                ):
                    data=service.snapshot().to_dict()
                rt=next(x for x in data['subsystems'] if x['subsystem']=='runtime')
                self.assertEqual(rt['state'],'degraded_evidence')
                self.assertNotIn(secret,rt['summary'])
                self.assertIn('<REDACTED>',rt['summary'])
                self.assertIn('error_digest=',rt['summary'])
                self.assertEqual(
                    rt['reason_codes'],
                    ['runtime_transaction_in_progress','runtime_history_tail_mismatch'],
                )
            finally: store.close()


if __name__=='__main__': unittest.main()
