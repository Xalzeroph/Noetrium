from __future__ import annotations

import math
import sqlite3
from typing import Callable

from ..api.errors import TelemetryMetricCorruptionError
from ..api.ports import TelemetryStorageReadRow


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise TelemetryMetricCorruptionError(f"{label} must be a string")
    return value


def _optional_string(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label=label)


def _finite_number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TelemetryMetricCorruptionError(f"{label} must be numeric")
    decoded = float(value)
    if not math.isfinite(decoded):
        raise TelemetryMetricCorruptionError(f"{label} must be finite")
    return decoded


class TelemetryReadSession:
    """Explicit read connection for one or many operator queries."""

    def __init__(self, connect: Callable[[], sqlite3.Connection]) -> None:
        self.db = connect()
        self._closed = False

    @staticmethod
    def _decode_row(row: tuple[object, ...]) -> TelemetryStorageReadRow:
        if len(row) != 13:
            raise TelemetryMetricCorruptionError("telemetry SQLite row has an invalid field count")
        sequence = row[0]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
            raise TelemetryMetricCorruptionError("telemetry sequence must be a positive integer")
        return (
            sequence,
            _string(row[1], label="metric"),
            _finite_number(row[2], label="metric value"),
            _finite_number(row[3], label="metric timestamp"),
            _string(row[4], label="run_id"),
            _optional_string(row[5], label="task_id"),
            _optional_string(row[6], label="decision_cycle_id"),
            _string(row[7], label="trace_id"),
            _string(row[8], label="span_id"),
            _optional_string(row[9], label="operation_id"),
            _optional_string(row[10], label="component_id"),
            _string(row[11], label="participant_generations_json"),
            _string(row[12], label="dimensions_json"),
        )

    def query(
        self,
        *,
        run_id: str,
        metric: str | None,
        decision_cycle_id: str | None,
        limit: int,
    ) -> tuple[TelemetryStorageReadRow, ...]:
        """Decode every selected database row into one typed telemetry result.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: N is the requested result cardinality; a public query returning N typed rows must decode and materialize all N rows.
        """
        clauses = ["run_id=?"]
        args: list[object] = [run_id]
        if metric is not None:
            clauses.append("metric=?")
            args.append(metric)
        if decision_cycle_id is not None:
            clauses.append("decision_cycle_id=?")
            args.append(decision_cycle_id)
        args.append(limit)
        sql = (
            "SELECT sequence,metric,value,timestamp,run_id,task_id,"
            "decision_cycle_id,trace_id,span_id,operation_id,component_id,"
            "participant_generations_json,dimensions_json "
            "FROM metric_observations WHERE "
            + " AND ".join(clauses)
            + " ORDER BY sequence LIMIT ?"
        )
        rows = self.db.execute(sql, args).fetchall()
        return tuple(self._decode_row(row) for row in rows)

    def count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM metric_observations").fetchone()[0])

    def close(self) -> None:
        if not self._closed:
            self.db.close()
            self._closed = True

    def __enter__(self) -> "TelemetryReadSession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


__all__ = ["TelemetryReadSession"]
