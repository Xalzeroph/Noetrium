from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.forensics.runtime.diagnostic_adapter import ForensicDiagnosticEvidence
from noetrium_platform.infrastructure.reliability.forensics.composition.incident_adapter import ForensicIncidentProjection
from noetrium_platform.infrastructure.reliability.failure.api import build_failure
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.infrastructure.reliability.diagnostics.runtime import DebugSnapshotService, IncidentService


def failure(run,msg):
    return build_failure(
        component_id="llm",failure_domain="LLM",failure_code="TIMEOUT",stage="request",
        context=ExecutionContext(run,"trace","span"),exc=TimeoutError(msg),operation_type="llm.request",
    )


class IncidentProjectionSyncV93Tests(unittest.TestCase):
    def test_first_incident_query_sees_all_authoritative_failures_not_only_opened_one(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"forensics"
            with ForensicStore(root) as store:
                f1=failure("r1","request 123456 timeout")
                f2=failure("r2","request 987654 timeout")
                store.append_failure(f1); store.append_failure(f2)
            with ForensicStore(root,read_only=True) as store:
                report=IncidentService(ForensicDiagnosticEvidence(store), ForensicIncidentProjection(store.failures, Path(td)/"incidents.sqlite3"), DebugSnapshotService(ForensicDiagnosticEvidence(store))).capture(f1.failure_id)
                self.assertEqual(report.recurrence_count,2)
                self.assertTrue(report.recurring)
                self.assertIn(f2.failure_id,report.similar_failure_ids)


    def test_incident_sync_uses_bounded_streaming_api_not_materialized_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"forensics"; db=Path(td)/"incidents.sqlite3"
            with ForensicStore(root) as store:
                rows=[failure(f"r{i}",f"request {100000+i} timeout") for i in range(7)]
                for row in rows:
                    store.append_failure(row)
            with ForensicStore(root,read_only=True) as store:
                projection=ForensicIncidentProjection(store.failures, db)
                with mock.patch.object(
                    store.failures,
                    "verified_payloads_after",
                    side_effect=AssertionError("materialized suffix must not be used"),
                ):
                    sync=projection.synchronize()
                self.assertEqual(sync.added_failures,7)
                self.assertEqual(sync.source_rows,7)

    def test_incremental_sync_adds_only_new_failure_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"forensics"; db=Path(td)/"incidents.sqlite3"
            with ForensicStore(root) as store:
                f1=failure("r1","request 123456 timeout"); store.append_failure(f1)
            with ForensicStore(root,read_only=True) as store:
                svc=IncidentService(ForensicDiagnosticEvidence(store), ForensicIncidentProjection(store.failures, db), DebugSnapshotService(ForensicDiagnosticEvidence(store))); a=svc.capture(f1.failure_id)
                self.assertEqual(a.recurrence_count,1)
            with ForensicStore(root) as store:
                f2=failure("r2","request 987654 timeout"); store.append_failure(f2)
            with ForensicStore(root,read_only=True) as store:
                svc=IncidentService(ForensicDiagnosticEvidence(store), ForensicIncidentProjection(store.failures, db), DebugSnapshotService(ForensicDiagnosticEvidence(store))); b=svc.capture(f2.failure_id)
                self.assertEqual(b.recurrence_count,2)
                sync=svc.incidents.synchronize()
                self.assertEqual(sync.added_failures,0)

if __name__=="__main__": unittest.main()
