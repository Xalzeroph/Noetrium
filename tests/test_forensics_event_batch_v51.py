from pathlib import Path
import tempfile, unittest
from unittest import mock

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.evidence.observability.api import EventEnvelope
from noetrium_platform.infrastructure.reliability.failure.api import build_failure
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


class ForensicsEventBatchV51Tests(unittest.TestCase):
    def ctx(self): return ExecutionContext('r','t','s')

    def test_events_batch_into_one_projection_transaction(self):
        with tempfile.TemporaryDirectory() as td:
            with ForensicStore(Path(td)) as store:
                with mock.patch.object(store.index,'project_events_batch',wraps=store.index.project_events_batch) as project:
                    for i in range(31): store.append_event(EventEnvelope(f'e{i}', 'x', self.ctx(), 'c'))
                    self.assertEqual(project.call_count,0); self.assertEqual(store.projection_backlog(),31)
                    store.append_event(EventEnvelope('e31', 'x', self.ctx(), 'c'))
                    self.assertEqual(project.call_count,1); self.assertEqual(store.projection_backlog(),0)

    def test_failure_forces_pending_events_visible_before_failure_projection(self):
        with tempfile.TemporaryDirectory() as td:
            with ForensicStore(Path(td)) as store:
                for i in range(3): store.append_event(EventEnvelope(f'e{i}', 'x', self.ctx(), 'c'))
                self.assertEqual(store.projection_backlog(),3)
                failure=build_failure(component_id='c',failure_domain='D',failure_code='X',stage='s',context=self.ctx(),exc=RuntimeError('x'))
                store.append_failure(failure)
                self.assertEqual(store.projection_backlog(),0)
                self.assertIsNotNone(store.index.locate('e2')); self.assertIsNotNone(store.index.locate(failure.failure_id))

    def test_close_flushes_event_projection_backlog(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); store=ForensicStore(root); store.append_event(EventEnvelope('e', 'x', self.ctx(), 'c')); self.assertEqual(store.projection_backlog(),1); store.close()
            with ForensicStore(root,read_only=True) as ro: self.assertIsNotNone(ro.index.locate('e'))

if __name__=='__main__': unittest.main()
