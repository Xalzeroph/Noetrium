from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest import mock

from tests._concurrency_support import telemetry_backend
from noetrium_platform.infrastructure.reliability.forensics.providers import HashChainError, HashChainedJSONL
import noetrium_platform.infrastructure.reliability.forensics.providers.hashlog as hashlog_module
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.evidence.observability.telemetry.metric.composition import build_default_registry
from noetrium_platform.evidence.observability.telemetry.metric.runtime import TelemetryBatchRecorder, TelemetryStore
from noetrium_platform.evidence.observability.telemetry.metric.providers.sqlite_schema import initialize_telemetry_schema


class IOPerformanceContractTests(unittest.TestCase):
    def test_hash_append_scans_once_not_once_per_row(self):
        with tempfile.TemporaryDirectory() as td:
            log=HashChainedJSONL(Path(td)/"x.jsonl",fsync_every=64)
            original=hashlog_module.scan_hash_chain
            with mock.patch.object(hashlog_module,"scan_hash_chain",wraps=original) as scan:
                for i in range(200): log.append({"i":i})
                self.assertEqual(scan.call_count,1)
            self.assertEqual(log.cached_tail[0],200)
            self.assertEqual(log.verify()[0],200)

    def test_external_same_lifetime_mutation_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"x.jsonl"; log=HashChainedJSONL(p); log.append({"i":1})
            # Valid external append from another writer is still an ownership violation.
            other=HashChainedJSONL(p); other.append({"i":2})
            with self.assertRaises(HashChainError): log.append({"i":3})

    def test_batch_telemetry_writes_one_transaction_per_batch(self):
        with tempfile.TemporaryDirectory() as td:
            store=TelemetryStore(build_default_registry(), telemetry_backend(self, Path(td)/"m.sqlite3")); ctx=ExecutionContext(run_id="r",trace_id="t",span_id="s")
            with TelemetryBatchRecorder(store,batch_size=100) as rec:
                for _ in range(1000): rec.observe(ctx,"llm.tokens.input",1,role="planner",model="m")
                self.assertEqual(rec.buffered,0)
            self.assertEqual(store.count(),1000)
            rows=store.query(run_id="r",metric="llm.tokens.input",limit=1001); self.assertEqual(len(rows),1000); self.assertEqual(rows[0]["sequence"],1); self.assertEqual(rows[-1]["sequence"],1000)

    def test_telemetry_query_indexes_avoid_temp_ordering(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.sqlite3"
            queries = (
                ("SELECT sequence FROM metric_observations WHERE run_id=? ORDER BY sequence LIMIT ?", ("r", 10)),
                ("SELECT sequence FROM metric_observations WHERE run_id=? AND metric=? ORDER BY sequence LIMIT ?", ("r", "m", 10)),
                ("SELECT sequence FROM metric_observations WHERE run_id=? AND decision_cycle_id=? ORDER BY sequence LIMIT ?", ("r", "d", 10)),
            )
            db = sqlite3.connect(path)
            try:
                initialize_telemetry_schema(db)
                for sql, args in queries:
                    plan = " ".join(
                        str(row[3]) for row in db.execute("EXPLAIN QUERY PLAN " + sql, args).fetchall()
                    )
                    self.assertNotIn("USE TEMP B-TREE FOR ORDER BY", plan)
            finally:
                db.close()

    def test_batch_is_retained_if_commit_fails(self):
        with tempfile.TemporaryDirectory() as td:
            store=TelemetryStore(build_default_registry(), telemetry_backend(self, Path(td)/"m.sqlite3")); ctx=ExecutionContext(run_id="r",trace_id="t",span_id="s"); rec=TelemetryBatchRecorder(store,batch_size=10)
            for _ in range(3): rec.observe(ctx,"llm.tokens.input",1,role="planner",model="m")
            with mock.patch.object(rec._session,"insert_many",side_effect=OSError("disk failure")):
                with self.assertRaises(OSError): rec.flush()
            self.assertEqual(rec.buffered,3); self.assertEqual(store.count(),0)

    def test_failed_commit_cleanup_does_not_mask_primary_failure(self):
        with tempfile.TemporaryDirectory() as td:
            store=TelemetryStore(build_default_registry(), telemetry_backend(self, Path(td)/"m.sqlite3")); ctx=ExecutionContext(run_id="r",trace_id="t",span_id="s"); rec=TelemetryBatchRecorder(store,batch_size=10)
            for _ in range(3): rec.observe(ctx,"llm.tokens.input",1,role="planner",model="m")
            session = rec._session
            self.assertIsNotNone(session)
            with mock.patch.object(session,"insert_many",side_effect=OSError("primary commit failure")), mock.patch.object(session,"close",side_effect=PermissionError("cleanup failure")):
                with self.assertRaisesRegex(OSError,"primary commit failure") as caught:
                    rec.flush()
            notes = getattr(caught.exception,"__notes__",())
            self.assertTrue(any("cleanup" in note for note in notes))
            self.assertEqual(rec.buffered,3); self.assertEqual(store.count(),0)
            self.assertIsNone(rec._session)
            self.assertEqual(len(rec.flush()),3); self.assertEqual(store.count(),3)
            rec.close()

    def test_failed_close_keeps_pending_batch_retryable(self):
        with tempfile.TemporaryDirectory() as td:
            store=TelemetryStore(build_default_registry(), telemetry_backend(self, Path(td)/"m.sqlite3")); ctx=ExecutionContext(run_id="r",trace_id="t",span_id="s"); rec=TelemetryBatchRecorder(store,batch_size=10)
            for _ in range(3): rec.observe(ctx,"llm.tokens.input",1,role="planner",model="m")
            with mock.patch.object(rec._session,"insert_many",side_effect=OSError("disk failure")):
                with self.assertRaises(OSError): rec.close()
            self.assertEqual(rec.buffered,3); self.assertEqual(store.count(),0)
            self.assertEqual(len(rec.flush()),3)
            self.assertEqual(rec.buffered,0); self.assertEqual(store.count(),3)
            rec.close()

    def test_writer_session_close_failure_remains_retryable(self):
        with tempfile.TemporaryDirectory() as td:
            store=TelemetryStore(build_default_registry(), telemetry_backend(self, Path(td)/"m.sqlite3")); rec=TelemetryBatchRecorder(store,batch_size=10)
            session = rec._session
            self.assertIsNotNone(session)
            with mock.patch.object(session,"close",side_effect=[PermissionError("busy"),None]) as close:
                with self.assertRaisesRegex(PermissionError,"busy"):
                    rec.close()
                self.assertFalse(rec._closed)
                self.assertIs(rec._session,session)
                rec.close()
                self.assertEqual(close.call_count,2)
            self.assertTrue(rec._closed)
            self.assertIsNone(rec._session)
    def test_context_exit_does_not_replace_primary_failure_with_telemetry_failure(self):
        with tempfile.TemporaryDirectory() as td:
            store=TelemetryStore(build_default_registry(), telemetry_backend(self, Path(td)/"m.sqlite3")); ctx=ExecutionContext(run_id="r",trace_id="t",span_id="s"); rec=TelemetryBatchRecorder(store,batch_size=10)
            for _ in range(3): rec.observe(ctx,"llm.tokens.input",1,role="planner",model="m")
            with mock.patch.object(rec._session,"insert_many",side_effect=OSError("telemetry disk failure")):
                with self.assertRaisesRegex(RuntimeError,"primary failure") as caught:
                    with rec:
                        raise RuntimeError("primary failure")
            notes = getattr(caught.exception,"__notes__",())
            self.assertTrue(any("telemetry" in note for note in notes))
            self.assertEqual(rec.buffered,3); self.assertEqual(store.count(),0)
            self.assertEqual(len(rec.flush()),3)
            rec.close()

if __name__=='__main__': unittest.main()
