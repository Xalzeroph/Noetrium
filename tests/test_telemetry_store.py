from pathlib import Path
import math
import sqlite3
import tempfile
import unittest
from threading import Event, Thread
from unittest import mock

from tests._concurrency_support import telemetry_backend
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.evidence.observability.telemetry.metric.api import TelemetryMetricCorruptionError
from noetrium_platform.evidence.observability.telemetry.metric.composition import build_default_registry
from noetrium_platform.evidence.observability.telemetry.metric.runtime import TelemetryAudit, TelemetryStore


class TelemetryStoreTests(unittest.TestCase):
    def _ctx(self):
        return ExecutionContext(run_id="run_1",trace_id="trace_1",span_id="span_1",task_id="task_99",decision_cycle_id="dc_77",operation_id="op_42",component_id="llm.runtime")

    def test_default_catalog_is_broad_and_low_cardinality_clean(self):
        r=build_default_registry()
        self.assertGreaterEqual(len(r.names()),100)
        self.assertEqual(TelemetryAudit(r).run(),())

    def test_persistent_store_keeps_high_cardinality_context_outside_dimensions(self):
        with tempfile.TemporaryDirectory() as td:
            r=build_default_registry(); store=TelemetryStore(r, telemetry_backend(self, Path(td)/"metrics.sqlite3")); ctx=self._ctx()
            seq=store.observe(ctx,"llm.request.latency",0.25,role="planner",model="qwen",endpoint="local",status="success")
            self.assertEqual(seq,1); self.assertEqual(store.count(),1)
            row=store.query(run_id="run_1",decision_cycle_id="dc_77")[0]
            self.assertEqual(row["task_id"],"task_99"); self.assertEqual(row["operation_id"],"op_42")
            self.assertNotIn("task_id",row["dimensions"]); self.assertEqual(row["dimensions"]["role"],"planner")

    def test_nonfinite_negative_counter_and_bad_ratio_are_rejected(self):
        r=build_default_registry(); ctx=self._ctx()
        with tempfile.TemporaryDirectory() as td:
            store=TelemetryStore(r, telemetry_backend(self, Path(td)/"m.sqlite3"))
            with self.assertRaises(ValueError): store.observe(ctx,"llm.request.latency",math.nan,role="planner",model="m",endpoint="e",status="x")
            with self.assertRaises(ValueError): store.observe(ctx,"llm.tokens.input",-1,role="planner",model="m")
            with self.assertRaises(ValueError): store.observe(ctx,"gpu.utilization",1.2,gpu="0",model_service="s")
            self.assertEqual(store.count(),0)

    def test_reader_connection_has_no_write_authority(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.sqlite3"
            backend = telemetry_backend(self, path)
            store = TelemetryStore(build_default_registry(), backend)
            store.observe(self._ctx(), "llm.tokens.input", 1, role="planner", model="m")
            with backend.reader_session() as reader:
                self.assertEqual(reader.db.execute("PRAGMA query_only").fetchone()[0], 1)
                with self.assertRaises(sqlite3.OperationalError):
                    reader.db.execute("DELETE FROM metric_observations")

    def test_persisted_metric_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.sqlite3"
            store = TelemetryStore(build_default_registry(), telemetry_backend(self, path))
            store.observe(self._ctx(), "llm.tokens.input", 1, role="planner", model="m")
            db = sqlite3.connect(path)
            try:
                with db:
                    db.execute("UPDATE metric_observations SET dimensions_json='1'")
            finally:
                db.close()
            with self.assertRaises(TelemetryMetricCorruptionError):
                store.query(run_id="run_1")

    def test_persisted_metric_scalar_type_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.sqlite3"
            store = TelemetryStore(build_default_registry(), telemetry_backend(self, path))
            store.observe(self._ctx(), "llm.tokens.input", 1, role="planner", model="m")
            db = sqlite3.connect(path)
            try:
                with db:
                    db.execute("UPDATE metric_observations SET value='not-a-number'")
            finally:
                db.close()
            with self.assertRaises(TelemetryMetricCorruptionError):
                store.query(run_id="run_1")

    def test_persisted_metric_duplicate_dimension_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.sqlite3"
            store = TelemetryStore(build_default_registry(), telemetry_backend(self, path))
            store.observe(self._ctx(), "llm.tokens.input", 1, role="planner", model="m")
            db = sqlite3.connect(path)
            try:
                with db:
                    db.execute(
                        "UPDATE metric_observations SET dimensions_json=?",
                        ('{"role":"planner","role":"critic","model":"m"}',),
                    )
            finally:
                db.close()
            with self.assertRaises(TelemetryMetricCorruptionError):
                store.query(run_id="run_1")

    def test_persisted_metric_duplicate_participant_generation_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.sqlite3"
            store = TelemetryStore(build_default_registry(), telemetry_backend(self, path))
            store.observe(self._ctx(), "llm.tokens.input", 1, role="planner", model="m")
            db = sqlite3.connect(path)
            try:
                with db:
                    db.execute(
                        "UPDATE metric_observations SET participant_generations_json=?",
                        ('{"agent":"g1","agent":"g2"}',),
                    )
            finally:
                db.close()
            with self.assertRaises(TelemetryMetricCorruptionError):
                store.query(run_id="run_1")

    def test_writer_close_waits_for_prechecked_insert_to_linearize(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.sqlite3"
            backend = telemetry_backend(self, path)
            store = TelemetryStore(build_default_registry(), backend)
            session = store.writer_session()
            pending = (
                store.prepare(self._ctx(), "llm.tokens.input", 1, role="planner", model="m"),
            )
            backend_session = session._backend_session
            original_call = backend_session._actor.call
            insert_waiting = Event()
            release_insert = Event()
            close_done = Event()
            errors: list[BaseException] = []

            def gated_call(operation, fn, /, *args, **kwargs):
                if operation == "insert-many":
                    insert_waiting.set()
                    if not release_insert.wait(5):
                        raise TimeoutError("insert gate timed out")
                return original_call(operation, fn, *args, **kwargs)

            def insert() -> None:
                try:
                    session.insert_many(pending)
                except BaseException as exc:
                    errors.append(exc)

            def close() -> None:
                try:
                    session.close()
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    close_done.set()

            with mock.patch.object(backend_session._actor, "call", side_effect=gated_call):
                insert_thread = Thread(target=insert)
                close_thread = Thread(target=close)
                insert_thread.start()
                self.assertTrue(insert_waiting.wait(5))
                close_thread.start()
                try:
                    self.assertFalse(
                        close_done.wait(0.5),
                        "close returned before an in-flight insert linearized",
                    )
                finally:
                    release_insert.set()
                    insert_thread.join(5)
                    close_thread.join(5)

            self.assertFalse(insert_thread.is_alive())
            self.assertFalse(close_thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(store.count(), 1)
            with self.assertRaises(RuntimeError):
                session.insert_many(pending)

    def test_backend_close_failure_is_retryable_without_reopening_writes(self):
        with tempfile.TemporaryDirectory() as td:
            backend = telemetry_backend(self, Path(td) / "m.sqlite3")
            session = backend.writer_session()
            original_close = session.close
            calls = 0

            def fail_once() -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("simulated session close failure")
                original_close()

            with mock.patch.object(session, "close", side_effect=fail_once):
                with self.assertRaises(ExceptionGroup):
                    backend.close()
                with self.assertRaises(RuntimeError):
                    backend.writer_session()
                backend.close()

            self.assertEqual(calls, 2)
            with self.assertRaises(RuntimeError):
                backend.writer_session()

    def test_high_card_id_still_rejected_as_metric_dimension(self):
        r=build_default_registry(); ctx=self._ctx()
        with tempfile.TemporaryDirectory() as td:
            store=TelemetryStore(r, telemetry_backend(self, Path(td)/"m.sqlite3"))
            with self.assertRaises(ValueError):
                store.observe(ctx,"operation.latency",1.0,component="c",operation="o",status="ok",request_id="r1")

if __name__ == "__main__": unittest.main()
