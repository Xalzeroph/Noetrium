from __future__ import annotations

import json
import sqlite3

from noetrium_platform.infrastructure.reliability.diagnostics.api import OperationInvocationRecord


_COLUMNS = (
    "invocation_id",
    "operation_id",
    "operation_type",
    "run_id",
    "task_id",
    "decision_cycle_id",
    "trace_id",
    "span_id",
    "caller_component_id",
    "target_component_id",
    "started_event_id",
    "started_at",
    "terminal_event_id",
    "terminal_event_type",
    "terminal_at",
    "status",
    "failure_id",
    "latest_payload_json",
)
_SELECT = ",".join(_COLUMNS)


def _record(row: tuple[object, ...]) -> OperationInvocationRecord:
    if len(row) != len(_COLUMNS):
        raise ValueError("operation invocation projection row has invalid width")
    *columns, payload_json = row
    payload = json.loads(str(payload_json))
    if not isinstance(payload, dict):
        raise ValueError("operation invocation payload must decode to an object")
    (
        invocation_id,
        operation_id,
        operation_type,
        run_id,
        task_id,
        decision_cycle_id,
        trace_id,
        span_id,
        caller_component_id,
        target_component_id,
        started_event_id,
        started_at,
        terminal_event_id,
        terminal_event_type,
        terminal_at,
        status,
        failure_id,
    ) = columns
    return OperationInvocationRecord(
        invocation_id=str(invocation_id),
        operation_id=str(operation_id),
        operation_type=str(operation_type),
        run_id=None if run_id is None else str(run_id),
        task_id=None if task_id is None else str(task_id),
        decision_cycle_id=None if decision_cycle_id is None else str(decision_cycle_id),
        trace_id=None if trace_id is None else str(trace_id),
        span_id=None if span_id is None else str(span_id),
        caller_component_id=None if caller_component_id is None else str(caller_component_id),
        target_component_id=None if target_component_id is None else str(target_component_id),
        started_event_id=None if started_event_id is None else str(started_event_id),
        started_at=None if started_at is None else float(started_at),
        terminal_event_id=None if terminal_event_id is None else str(terminal_event_id),
        terminal_event_type=None if terminal_event_type is None else str(terminal_event_type),
        terminal_at=None if terminal_at is None else float(terminal_at),
        status=None if status is None else str(status),
        failure_id=None if failure_id is None else str(failure_id),
        payload=payload,
    )


def operation_invocation(
    conn: sqlite3.Connection,
    invocation_id: str,
) -> OperationInvocationRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM operation_invocations WHERE invocation_id=?",
        (invocation_id,),
    ).fetchone()
    return _record(row) if row else None


def unclosed_operations(
    conn: sqlite3.Connection,
    *,
    run_id: str | None = None,
    limit: int = 100,
) -> tuple[OperationInvocationRecord, ...]:
    if limit <= 0:
        return ()
    where = "started_at IS NOT NULL AND terminal_at IS NULL"
    args: tuple[object, ...]
    if run_id is None:
        args = (limit,)
    else:
        where += " AND run_id=?"
        args = (run_id, limit)
    rows = conn.execute(
        f"SELECT {_SELECT} FROM operation_invocations "
        f"WHERE {where} ORDER BY started_at DESC LIMIT ?",
        args,
    ).fetchall()
    return tuple(_record(row) for row in rows)


def operations_open_at(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    timestamp: float,
    limit: int = 100,
) -> tuple[OperationInvocationRecord, ...]:
    """Return invocations that were open at an exact historical instant.

    This is temporal correlation, not proof that an open invocation caused a failure.
    """
    if limit <= 0:
        return ()
    rows = conn.execute(
        f"SELECT {_SELECT} FROM operation_invocations "
        "WHERE run_id=? AND started_at IS NOT NULL AND started_at<=? "
        "AND (terminal_at IS NULL OR terminal_at>?) "
        "ORDER BY started_at DESC LIMIT ?",
        (run_id, timestamp, timestamp, limit),
    ).fetchall()
    return tuple(_record(row) for row in rows)


__all__ = ["operation_invocation", "operations_open_at", "unclosed_operations"]
