from pathlib import Path
import tempfile,unittest
from unittest import mock
from tests._concurrency_support import OwnedForensicStore as ForensicStore, owned_task_group
from noetrium_platform.infrastructure.reliability.forensics.runtime import ForensicProjectionError
from noetrium_platform.infrastructure.reliability.failure.api import build_failure
from noetrium_platform.foundation.kernel.kernel import ExecutionContext

class ForensicsProjectionV37Tests(unittest.TestCase):
    def test_hot_append_projects_object_and_freshness_in_one_projection_call(self):
        with tempfile.TemporaryDirectory() as td:
            with ForensicStore(Path(td)) as store:
                ctx=ExecutionContext(run_id='r',trace_id='t',span_id='s')
                f=build_failure(component_id='c',failure_domain='D',failure_code='X',stage='s',context=ctx,exc=RuntimeError('x'))
                with mock.patch.object(store.index,'project_failure',wraps=store.index.project_failure) as project:
                    store.append_failure(f); self.assertEqual(project.call_count,1)
                self.assertTrue(store.index_freshness()[0])
    def test_projection_failure_is_explicit_and_authoritative_tail_remains_rebuildable(self):
        with tempfile.TemporaryDirectory() as td:
            with ForensicStore(Path(td)) as store:
                ctx=ExecutionContext(run_id='r',trace_id='t',span_id='s')
                f=build_failure(component_id='c',failure_domain='D',failure_code='X',stage='s',context=ctx,exc=RuntimeError('x'))
                with mock.patch.object(store.index,'project_failure',side_effect=OSError('sqlite down')):
                    with self.assertRaises(ForensicProjectionError): store.append_failure(f)
                self.assertEqual(store.failures.verify()[0],1)
                self.assertFalse(store.index_freshness()[0])

if __name__=='__main__': unittest.main()

class RebuildLifecycleV37Tests(unittest.TestCase):
    def test_rebuild_closes_writer_before_replace(self):
        from noetrium_platform.evidence.observability.api import EventEnvelope
        from noetrium_platform.infrastructure.reliability.forensics.composition import rebuild_forensic_index, inspect_index_freshness
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with ForensicStore(root) as store:
                ctx=ExecutionContext(run_id='r',trace_id='t',span_id='s')
                store.append_event(EventEnvelope('e1', 'x', ctx, 'c'))
            report=rebuild_forensic_index(root, task_group=owned_task_group("forensic-rebuild"))
            self.assertEqual(report.objects,1)
            self.assertTrue(inspect_index_freshness(root).fresh)
