from pathlib import Path
import tempfile,unittest
from unittest import mock
from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.forensics.runtime.diagnostic_adapter import ForensicDiagnosticEvidence
from noetrium_platform.infrastructure.reliability.failure.api import build_failure
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.infrastructure.reliability.diagnostics.runtime import DebugSnapshotService

class ForensicReadSessionV38Tests(unittest.TestCase):
    def test_debug_snapshot_uses_one_forensic_read_connection(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with ForensicStore(root) as store:
                ctx=ExecutionContext(run_id='r',trace_id='t',span_id='s',task_id='task',decision_cycle_id='dc')
                f=build_failure(component_id='c',failure_domain='D',failure_code='X',stage='s',context=ctx,exc=RuntimeError('x')); store.append_failure(f)
            store=ForensicStore(root,read_only=True); original=store.index.db.connect
            with mock.patch.object(store.index.db,'connect',wraps=original) as connect:
                snap=DebugSnapshotService(ForensicDiagnosticEvidence(store)).build(f.failure_id)
                self.assertEqual(connect.call_count,1)
                self.assertEqual(snap.object_id,f.failure_id)

if __name__=='__main__':unittest.main()
