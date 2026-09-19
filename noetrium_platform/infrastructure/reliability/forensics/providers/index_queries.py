from __future__ import annotations

import sqlite3

from noetrium_platform.infrastructure.reliability.diagnostics.api import (
    DiagnosticObjectRecord,
    StateWriterRecord,
)

from .index_record_codec import (
    OBJECT_SELECT,
    STATE_SELECT,
    decode_object_record,
    decode_state_writer_record,
)


def freshness(conn: sqlite3.Connection) -> dict[str, tuple[int, str]]:
    rows = conn.execute(
        "SELECT ledger,rows,tail_hash FROM ledger_freshness ORDER BY ledger"
    ).fetchall()
    return {str(name): (int(count), str(tail)) for name, count, tail in rows}


def locate(
    conn: sqlite3.Connection,
    object_id: str,
) -> DiagnosticObjectRecord | None:
    row = conn.execute(
        f"SELECT {OBJECT_SELECT} FROM object_index WHERE object_id=?",
        (object_id,),
    ).fetchone()
    return decode_object_record(row) if row else None


def last_writer(
    conn: sqlite3.Connection,
    run_id: str,
    state_name: str,
) -> StateWriterRecord | None:
    row = conn.execute(
        f"SELECT {STATE_SELECT} FROM state_writers "
        "WHERE run_id=? AND state_name=? ORDER BY timestamp DESC LIMIT 1",
        (run_id, state_name),
    ).fetchone()
    return decode_state_writer_record(row) if row else None


def around(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    timestamp: float,
    seconds: float = 30.0,
) -> tuple[DiagnosticObjectRecord, ...]:
    if seconds < 0:
        raise ValueError("seconds must be non-negative")
    rows = conn.execute(
        f"SELECT {OBJECT_SELECT} FROM object_index "
        "WHERE run_id=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
        (run_id, timestamp - seconds, timestamp + seconds),
    ).fetchall()
    return tuple(decode_object_record(row) for row in rows)


def recent_state_writers(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    before: float,
    limit: int = 12,
) -> tuple[StateWriterRecord, ...]:
    if limit <= 0:
        return ()
    rows = conn.execute(
        f"SELECT {STATE_SELECT} FROM state_writers "
        "WHERE run_id=? AND timestamp<=? ORDER BY timestamp DESC LIMIT ?",
        (run_id, before, limit),
    ).fetchall()
    return tuple(decode_state_writer_record(row) for row in rows)


def related_to(
    conn: sqlite3.Connection,
    object_id: str,
    *,
    limit: int = 100,
) -> tuple[DiagnosticObjectRecord, ...]:
    if limit <= 0:
        return ()
    row = conn.execute(
        "SELECT run_id,task_id,decision_cycle_id,trace_id,span_id "
        "FROM object_index WHERE object_id=?",
        (object_id,),
    ).fetchone()
    if row is None:
        return ()
    run_id, task_id, decision_cycle_id, trace_id, span_id = row
    rows = conn.execute(
        f"SELECT {OBJECT_SELECT} FROM object_index WHERE "
        "((run_id=? ) OR (run_id IS NULL AND ? IS NULL)) AND ("
        "(? IS NOT NULL AND task_id=?) OR "
        "(? IS NOT NULL AND decision_cycle_id=?) OR "
        "(? IS NOT NULL AND trace_id=?) OR "
        "(? IS NOT NULL AND span_id=?) OR object_id=?) "
        "ORDER BY timestamp LIMIT ?",
        (
            run_id,
            run_id,
            task_id,
            task_id,
            decision_cycle_id,
            decision_cycle_id,
            trace_id,
            trace_id,
            span_id,
            span_id,
            object_id,
            limit,
        ),
    ).fetchall()
    return tuple(decode_object_record(item) for item in rows)


__all__ = [
    "around",
    "freshness",
    "last_writer",
    "locate",
    "recent_state_writers",
    "related_to",
]
