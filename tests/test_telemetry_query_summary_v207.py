from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from noetrium_platform.evidence.observability.telemetry.metric.api import TelemetryMetricCorruptionError
from noetrium_platform.evidence.observability.telemetry.metric.composition import build_default_registry
from noetrium_platform.evidence.observability.telemetry.metric.providers import SQLiteTelemetryReader
from noetrium_platform.evidence.observability.telemetry.metric.providers.sqlite_schema import initialize_telemetry_schema
from noetrium_platform.evidence.observability.telemetry.metric.runtime import TelemetryStore
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from tests._concurrency_support import telemetry_backend


class TelemetryQuerySummaryTests(unittest.TestCase):
    def _store(self, path: Path) -> TelemetryStore:
        return TelemetryStore(build_default_registry(), telemetry_backend(self, path))

    @staticmethod
    def _context() -> ExecutionContext:
        return ExecutionContext(run_id="summary-run", trace_id="trace", span_id="span")

    def test_query_returns_the_typed_metric_row_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "metrics.sqlite3"
            self._store(path).observe(
                self._context(),
                "operation.latency",
                3.5,
                component="c",
                operation="op",
                status="ok",
            )
            row = SQLiteTelemetryReader(path).query(run_id="summary-run")[0]
            self.assertEqual(
                set(row),
                {
                    "sequence", "metric", "value", "timestamp", "run_id", "task_id",
                    "decision_cycle_id", "trace_id", "span_id", "operation_id", "component_id",
                    "dimensions",
                },
            )
            self.assertEqual(row["metric"], "operation.latency")
            self.assertEqual(row["value"], 3.5)
            self.assertEqual(row["run_id"], "summary-run")
            self.assertEqual(row["dimensions"], {"component": "c", "operation": "op", "status": "ok"})

    def test_summary_preserves_linear_percentile_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "metrics.sqlite3"
            store = self._store(path)
            context = self._context()
            for value in range(1, 101):
                store.observe(context, "operation.latency", float(value), component="c", operation="op", status="ok")
            summary = SQLiteTelemetryReader(path).summarize(
                run_id="summary-run", metric="operation.latency"
            )
            self.assertEqual(summary.count, 100)
            self.assertEqual(summary.minimum, 1.0)
            self.assertEqual(summary.maximum, 100.0)
            self.assertAlmostEqual(summary.mean, 50.5)
            self.assertAlmostEqual(summary.p50, 50.5)
            self.assertAlmostEqual(summary.p95, 95.05)
            self.assertAlmostEqual(summary.p99, 99.01)


    def test_summary_fetches_all_percentile_positions_in_one_query(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "metrics.sqlite3"
            store = self._store(path)
            context = self._context()
            for value in range(1, 101):
                store.observe(
                    context, "operation.latency", float(value),
                    component="c", operation="op", status="ok",
                )

            statements: list[str] = []

            class TracingReader(SQLiteTelemetryReader):
                def _connect(self) -> sqlite3.Connection:
                    db = super()._connect()
                    db.set_trace_callback(statements.append)
                    return db

            summary = TracingReader(path).summarize(
                run_id="summary-run", metric="operation.latency"
            )
            self.assertAlmostEqual(summary.p99, 99.01)
            percentile_queries = [
                statement for statement in statements
                if "ROW_NUMBER() OVER (ORDER BY value)" in statement
            ]
            self.assertEqual(len(percentile_queries), 1)
            self.assertNotIn(" OFFSET ", percentile_queries[0])

    def test_summary_mean_preserves_sorted_accumulation_order(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "metrics.sqlite3"
            store = self._store(path)
            context = self._context()
            values = (1e16, 1.0, -1e16, 3.0)
            for value in values:
                store.observe(context, "operation.latency", value, component="c", operation="op", status="ok")
            summary = SQLiteTelemetryReader(path).summarize(
                run_id="summary-run", metric="operation.latency"
            )
            self.assertEqual(summary.mean, sum(sorted(values)) / len(values))

    def test_summary_ordering_uses_covering_value_index(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "metrics.sqlite3"
            db = sqlite3.connect(path)
            try:
                initialize_telemetry_schema(db)
                plan = " ".join(
                    str(row[3])
                    for row in db.execute(
                        "EXPLAIN QUERY PLAN SELECT value FROM metric_observations "
                        "WHERE run_id=? AND metric=? ORDER BY value",
                        ("r", "m"),
                    ).fetchall()
                )
                self.assertIn("idx_metric_run_name_value", plan)
                self.assertNotIn("USE TEMP B-TREE FOR ORDER BY", plan)
            finally:
                db.close()

    def test_summary_percentiles_use_one_database_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "metrics.sqlite3"
            store = self._store(path)
            context = self._context()
            for value in range(1, 21):
                store.observe(context, "operation.latency", float(value), component="c", operation="op", status="ok")
            reader = SQLiteTelemetryReader(path)
            real = reader._connect()

            class CountingConnection:
                def __init__(self, connection: sqlite3.Connection) -> None:
                    self.connection = connection
                    self.percentile_queries = 0

                def execute(self, sql: str, parameters=()):
                    if "WITH ranked AS" in sql:
                        self.percentile_queries += 1
                    return self.connection.execute(sql, parameters)

                def close(self) -> None:
                    self.connection.close()

            counted = CountingConnection(real)
            with patch.object(reader, "_connect", return_value=counted):
                summary = reader.summarize(run_id="summary-run", metric="operation.latency")
            self.assertAlmostEqual(summary.p95, 19.05)
            self.assertEqual(counted.percentile_queries, 1)

    def test_read_session_materializes_every_requested_typed_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "metrics.sqlite3"
            db = sqlite3.connect(path)
            try:
                initialize_telemetry_schema(db)
                with db:
                    for index in range(5):
                        db.execute(
                            "INSERT INTO metric_observations("
                            "metric,value,timestamp,run_id,trace_id,span_id,participant_generations_json,dimensions_json"
                            ") VALUES(?,?,?,?,?,?,?,?)",
                            ("latency", float(index + 1), float(index), "run", "trace", "span", "{}", "{}"),
                        )
            finally:
                db.close()
            from noetrium_platform.evidence.observability.telemetry.metric.providers.sqlite_reader import TelemetryReadSession
            session = TelemetryReadSession(lambda: sqlite3.connect(path))
            try:
                rows = session.query(run_id="run", metric="latency", decision_cycle_id=None, limit=5)
                self.assertEqual(len(rows), 5)
                self.assertEqual(tuple(row[0] for row in rows), (1, 2, 3, 4, 5))
            finally:
                session.close()

    def test_read_session_rejects_corrupt_tail_row_in_requested_result(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "metrics.sqlite3"
            db = sqlite3.connect(path)
            try:
                initialize_telemetry_schema(db)
                with db:
                    for index in range(5):
                        db.execute(
                            "INSERT INTO metric_observations("
                            "metric,value,timestamp,run_id,trace_id,span_id,participant_generations_json,dimensions_json"
                            ") VALUES(?,?,?,?,?,?,?,?)",
                            ("latency", float(index + 1), float(index), "run", "trace", "span", "{}", "{}"),
                        )
                    db.execute(
                        "UPDATE metric_observations SET metric=? WHERE sequence=(SELECT MAX(sequence) FROM metric_observations)",
                        (sqlite3.Binary(b"latency"),),
                    )
            finally:
                db.close()
            from noetrium_platform.evidence.observability.telemetry.metric.providers.sqlite_reader import TelemetryReadSession
            session = TelemetryReadSession(lambda: sqlite3.connect(path))
            try:
                with self.assertRaises(TelemetryMetricCorruptionError):
                    session.query(run_id="run", metric=None, decision_cycle_id=None, limit=5)
            finally:
                session.close()

    def test_reader_rejects_corrupt_json_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "metrics.sqlite3"
            store = self._store(path)
            store.observe(
                self._context(), "llm.tokens.input", 1.0, role="planner", model="m"
            )
            db = sqlite3.connect(path)
            try:
                with db:
                    db.execute("UPDATE metric_observations SET dimensions_json='1'")
            finally:
                db.close()
            with self.assertRaises(TelemetryMetricCorruptionError):
                SQLiteTelemetryReader(path).query(run_id="summary-run")

    def test_reader_rejects_duplicate_dimension_keys(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "metrics.sqlite3"
            store = self._store(path)
            store.observe(
                self._context(), "llm.tokens.input", 1.0, role="planner", model="m"
            )
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
                SQLiteTelemetryReader(path).query(run_id="summary-run")

    def test_summary_rejects_corrupt_non_numeric_value(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "metrics.sqlite3"
            store = self._store(path)
            store.observe(
                self._context(), "llm.tokens.input", 1.0, role="planner", model="m"
            )
            db = sqlite3.connect(path)
            try:
                with db:
                    db.execute("UPDATE metric_observations SET value='not-a-number'")
            finally:
                db.close()
            with self.assertRaises(TelemetryMetricCorruptionError):
                SQLiteTelemetryReader(path).summarize(
                    run_id="summary-run", metric="llm.tokens.input"
                )


if __name__ == "__main__":
    unittest.main()
