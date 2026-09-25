from pathlib import Path
import tempfile, unittest

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.failure.api import RecoveryAction

from noetrium_platform.infrastructure.reliability.forensics.runtime.diagnostic_adapter import ForensicDiagnosticEvidence
from noetrium_platform.infrastructure.reliability.forensics.composition.incident_adapter import ForensicIncidentProjection
from noetrium_platform.infrastructure.reliability.failure.api import build_failure
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.infrastructure.reliability.diagnostics.runtime import DebugSnapshotService, IncidentService

class IncidentOSV32Tests(unittest.TestCase):
    def _ctx(self,run='r1'):
        return ExecutionContext(run_id=run,trace_id='tr',span_id='sp',task_id='task1',decision_cycle_id='dc1',operation_id='op1',component_id='llm.runtime')
    def _failure(self,ctx,msg):
        return build_failure(component_id='llm.runtime',failure_domain='LLM',failure_code='TIMEOUT',stage='request',context=ctx,exc=TimeoutError(msg),operation_id='op1',operation_type='llm.request',recommended_recovery=RecoveryAction.RETRY_OPERATION)
    def test_same_bug_with_different_numeric_ids_clusters(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'forensics'
            with ForensicStore(root) as store:
                f1=self._failure(self._ctx('r1'),'provider timeout request 123456')
                f2=self._failure(self._ctx('r2'),'provider timeout request 987654')
                store.append_failure(f1); store.append_failure(f2)
            store=ForensicStore(root,read_only=True)
            svc=IncidentService(ForensicDiagnosticEvidence(store), ForensicIncidentProjection(store.failures, Path(td)/'incidents.sqlite3'), DebugSnapshotService(ForensicDiagnosticEvidence(store)))
            a=svc.capture(f1.failure_id); b=svc.capture(f2.failure_id)
            self.assertEqual(a.fingerprint,b.fingerprint); self.assertTrue(b.recurring); self.assertEqual(b.recurrence_count,2)
            self.assertIn(f1.failure_id,b.similar_failure_ids)
    def test_incident_includes_exact_debug_snapshot_and_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'forensics'
            with ForensicStore(root) as store:
                f=self._failure(self._ctx(),'provider timeout')
                store.append_failure(f)
            store=ForensicStore(root,read_only=True)
            report=IncidentService(ForensicDiagnosticEvidence(store), ForensicIncidentProjection(store.failures, Path(td)/'inc.sqlite3'), DebugSnapshotService(ForensicDiagnosticEvidence(store))).capture(f.failure_id)
            self.assertEqual(report.recovery,'retry_operation')
            self.assertIn('llm.runtime',report.exact_location)
            self.assertEqual(report.snapshot.object_id,f.failure_id)

if __name__=='__main__': unittest.main()
