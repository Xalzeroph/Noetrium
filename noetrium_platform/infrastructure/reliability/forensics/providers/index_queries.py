from __future__ import annotations

import heapq
import sqlite3

from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    ComplexityBound,
    ComplexityContract,
    ComplexityFactor,
    ComplexityMonomial,
)
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


RELATED_OBJECT_QUERY_COMPLEXITY = ComplexityContract(
    algorithm_id="diagnostics.related-index.v2",
    implementation_digest=canonical_digest(
        ("diagnostics.related-index.v2", "indexed-constant-way-merge")
    ),
    time_upper_bound=ComplexityBound(
        (
            ComplexityMonomial(
                (
                    ComplexityFactor(
                        "indexed_objects",
                        power_numerator=0,
                        log_power=1,
                    ),
                )
            ),
            ComplexityMonomial((ComplexityFactor("related_limit"),)),
        )
    ),
    space_upper_bound=ComplexityBound.linear("related_limit"),
    assumptions=(
        "the six correlation dimensions are a fixed constant",
        "each correlation branch uses a (run_id,key,timestamp,object_id) B-tree index",
        "SQLite B-tree seek is logarithmic and each branch emits timestamp order without a temporary sort",
        "the result limit bounds rows pulled from every constant-number branch",
    ),
    time_lower_bound=ComplexityBound.linear("related_rows"),
    space_lower_bound=ComplexityBound.linear("related_rows"),
)

_RELATED_COLUMNS = (
    "task_id",
    "decision_cycle_id",
    "trace_id",
    "span_id",
    "graph_node_id",
    "graph_attempt_id",
)


def _diagnostic_order_key(
    record: DiagnosticObjectRecord,
) -> tuple[int, float, str]:
    # SQLite ascending order places NULL before numeric timestamps.  object_id
    # closes the tie deterministically and is part of each correlation index.
    return (
        0 if record.timestamp is None else 1,
        0.0 if record.timestamp is None else record.timestamp,
        record.object_id,
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


def locate_event_digest(
    conn: sqlite3.Connection,
    event_digest: str,
) -> DiagnosticObjectRecord | None:
    if (
        type(event_digest) is not str
        or len(event_digest) != 64
        or any(ch not in "0123456789abcdef" for ch in event_digest)
    ):
        raise ValueError("event_digest must be lowercase SHA-256")
    row = conn.execute(
        f"SELECT {OBJECT_SELECT} FROM object_index "
        "WHERE json_valid(payload_json) "
        "AND json_extract(payload_json, '$.event_digest')=? LIMIT 1",
        (event_digest,),
    ).fetchone()
    return decode_object_record(row) if row else None



def _causal_parent_digests(record: DiagnosticObjectRecord) -> tuple[str, ...]:
    payload = record.to_payload()
    raw = payload.get("causal_event_refs", ())
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError("diagnostic causal_event_refs must be a sequence")
    refs = tuple(raw)
    for ref in refs:
        if (
            type(ref) is not str
            or len(ref) != 64
            or any(ch not in "0123456789abcdef" for ch in ref)
        ):
            raise ValueError("diagnostic causal event ref must be lowercase SHA-256")
    return refs


def causal_cone(
    conn: sqlite3.Connection,
    object_id: str,
    *,
    limit: int = 1000,
) -> tuple[DiagnosticObjectRecord, ...]:
    """Return the reverse causal cone, beginning at the requested object.

    Parent lookups use the event-digest index, so cost scales with the causal
    cone rather than the global forensic corpus.
    """
    if limit <= 0:
        return ()
    root = locate(conn, object_id)
    if root is None:
        return ()
    result: list[DiagnosticObjectRecord] = []
    seen: set[str] = set()
    stack: list[DiagnosticObjectRecord] = [root]
    while stack and len(result) < limit:
        record = stack.pop()
        if record.object_id in seen:
            continue
        seen.add(record.object_id)
        result.append(record)
        parents: list[DiagnosticObjectRecord] = []
        for digest in _causal_parent_digests(record):
            parent = locate_event_digest(conn, digest)
            if parent is not None and parent.object_id not in seen:
                parents.append(parent)
        stack.extend(reversed(parents))
    return tuple(result)

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



def for_graph_node(
    conn: sqlite3.Connection,
    graph_node_id: str,
    *,
    limit: int = 1000,
) -> tuple[DiagnosticObjectRecord, ...]:
    if not graph_node_id.strip() or limit <= 0:
        return ()
    rows = conn.execute(
        f"SELECT {OBJECT_SELECT} FROM object_index "
        "WHERE graph_node_id=? ORDER BY timestamp LIMIT ?",
        (graph_node_id, limit),
    ).fetchall()
    return tuple(decode_object_record(row) for row in rows)


def related_to(
    conn: sqlite3.Connection,
    object_id: str,
    *,
    limit: int = 100,
) -> tuple[DiagnosticObjectRecord, ...]:
    """Return timestamp-ordered objects sharing any exact correlation key.

    K=6 correlation dimensions is fixed by the diagnostic schema.  Each
    non-null key performs one indexed range scan restricted to the root run,
    and the sorted streams are merged with a K-way heap.  This prevents query
    cost from scaling with every object in a large run.
    """

    if limit <= 0:
        return ()

    root_row = conn.execute(
        f"SELECT {OBJECT_SELECT} FROM object_index WHERE object_id=?",
        (object_id,),
    ).fetchone()
    if root_row is None:
        return ()
    root = decode_object_record(root_row)

    values = (
        root.task_id,
        root.decision_cycle_id,
        root.trace_id,
        root.span_id,
        root.graph_node_id,
        root.graph_attempt_id,
    )
    cursors: list[sqlite3.Cursor] = []
    heap: list[
        tuple[
            tuple[int, float, str],
            int,
            DiagnosticObjectRecord,
        ]
    ] = []

    # Root is a one-element stream because object_id itself is always related.
    heapq.heappush(heap, (_diagnostic_order_key(root), -1, root))

    for column, value in zip(_RELATED_COLUMNS, values, strict=True):
        if value is None:
            continue
        cursor = conn.execute(
            f"SELECT {OBJECT_SELECT} FROM object_index "
            f"WHERE run_id IS ? AND {column}=? "
            "ORDER BY timestamp, object_id LIMIT ?",
            (root.run_id, value, limit),
        )
        branch = len(cursors)
        cursors.append(cursor)
        row = cursor.fetchone()
        if row is None:
            continue
        record = decode_object_record(row)
        heapq.heappush(
            heap,
            (_diagnostic_order_key(record), branch, record),
        )

    result: list[DiagnosticObjectRecord] = []
    seen: set[str] = set()
    while heap and len(result) < limit:
        _key, branch, record = heapq.heappop(heap)
        if record.object_id not in seen:
            seen.add(record.object_id)
            result.append(record)
        if branch < 0:
            continue
        row = cursors[branch].fetchone()
        if row is not None:
            next_record = decode_object_record(row)
            heapq.heappush(
                heap,
                (_diagnostic_order_key(next_record), branch, next_record),
            )
    return tuple(result)


__all__ = [
    "around",
    "causal_cone",
    "for_graph_node",
    "freshness",
    "last_writer",
    "locate",
    "locate_event_digest",
    "recent_state_writers",
    "related_to",
    "RELATED_OBJECT_QUERY_COMPLEXITY",
]
