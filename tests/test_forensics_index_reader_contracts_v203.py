from __future__ import annotations

import json

import pytest

from noetrium_platform.foundation.kernel.kernel.complexity import ComplexityBound

from noetrium_platform.infrastructure.reliability.forensics.providers.index_db import ForensicIndexDB
from noetrium_platform.infrastructure.reliability.forensics.providers.index_reader import ForensicIndexReader


def _db(tmp_path) -> ForensicIndexDB:
    return ForensicIndexDB(tmp_path / "index.sqlite3", read_only=False)


def _insert_object(
    db: ForensicIndexDB,
    *,
    object_id: str,
    run_id: str | None,
    task_id: str | None,
    timestamp: float,
    payload: object,
) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO object_index("
            "object_id, kind, run_id, task_id, decision_cycle_id, trace_id, "
            "span_id, component_id, timestamp, payload_json"
            ") VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                object_id,
                "event",
                run_id,
                task_id,
                None,
                None,
                None,
                "component",
                timestamp,
                json.dumps(payload, sort_keys=True),
            ),
        )
        conn.commit()


def test_related_to_preserves_runless_object_correlation(tmp_path) -> None:
    db = _db(tmp_path)
    _insert_object(
        db,
        object_id="event-a",
        run_id=None,
        task_id="task-1",
        timestamp=1.0,
        payload={"event_id": "event-a"},
    )
    _insert_object(
        db,
        object_id="event-b",
        run_id=None,
        task_id="task-1",
        timestamp=2.0,
        payload={"event_id": "event-b"},
    )
    rows = ForensicIndexReader(db).related_to("event-a")
    assert tuple(row.object_id for row in rows) == ("event-a", "event-b")


def test_closed_read_session_fails_closed(tmp_path) -> None:
    reader = ForensicIndexReader(_db(tmp_path))
    session = reader.session()
    assert session.freshness() == {}
    session.close()
    session.close()
    with pytest.raises(RuntimeError, match="read session is closed"):
        session.freshness()
    with pytest.raises(RuntimeError, match="read session is closed"):
        session.__enter__()


def test_projection_payload_must_decode_to_object(tmp_path) -> None:
    db = _db(tmp_path)
    _insert_object(
        db,
        object_id="bad-payload",
        run_id="run-1",
        task_id=None,
        timestamp=1.0,
        payload=["not", "an", "object"],
    )
    with pytest.raises(ValueError, match="payload must decode to an object"):
        ForensicIndexReader(db).locate("bad-payload")


def test_read_session_enforces_sqlite_query_only(tmp_path) -> None:
    import sqlite3

    reader = ForensicIndexReader(_db(tmp_path))
    with reader.session() as session:
        conn = session._connection()
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute(
                "INSERT INTO ledger_freshness(ledger,rows,tail_hash) VALUES(?,?,?)",
                ("events", 0, "0" * 64),
            )


def test_negative_around_window_is_rejected(tmp_path) -> None:
    reader = ForensicIndexReader(_db(tmp_path))
    with pytest.raises(ValueError, match="seconds must be non-negative"):
        reader.around(run_id="run-1", timestamp=10.0, seconds=-0.1)


def test_forensic_index_upgrades_pre_graph_projection_before_index_creation(
    tmp_path,
) -> None:
    import sqlite3

    path = tmp_path / "index.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE object_index(
                object_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                run_id TEXT,
                task_id TEXT,
                decision_cycle_id TEXT,
                trace_id TEXT,
                span_id TEXT,
                component_id TEXT,
                timestamp REAL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE state_writers(
                mutation_id TEXT PRIMARY KEY,
                state_name TEXT NOT NULL,
                run_id TEXT NOT NULL,
                task_id TEXT,
                decision_cycle_id TEXT,
                trace_id TEXT,
                span_id TEXT,
                component_id TEXT NOT NULL,
                operation_id TEXT NOT NULL,
                new_version INTEGER NOT NULL,
                new_digest TEXT NOT NULL,
                timestamp REAL NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE operation_invocations(
                invocation_id TEXT PRIMARY KEY,
                operation_id TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                run_id TEXT,
                task_id TEXT,
                decision_cycle_id TEXT,
                trace_id TEXT,
                span_id TEXT,
                caller_component_id TEXT,
                target_component_id TEXT,
                started_event_id TEXT,
                started_at REAL,
                terminal_event_id TEXT,
                terminal_event_type TEXT,
                terminal_at REAL,
                status TEXT,
                failure_id TEXT,
                latest_payload_json TEXT NOT NULL
            );
            CREATE TABLE ledger_freshness(
                ledger TEXT PRIMARY KEY,
                rows INTEGER NOT NULL,
                tail_hash TEXT NOT NULL
            );
            """
        )
        db.execute(
            "INSERT INTO object_index VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "old-object",
                "legacy",
                "run",
                None,
                None,
                None,
                None,
                "component",
                1.0,
                "{}",
            ),
        )

    ForensicIndexDB(path, read_only=False)

    with sqlite3.connect(path) as db:
        columns = {
            str(row[1])
            for row in db.execute("PRAGMA table_info(object_index)")
        }
        assert {
            "research_revision_digest",
            "research_execution_id",
            "research_cut_id",
            "graph_node_id",
            "graph_attempt_id",
            "graph_generation",
        } <= columns
        indexes = {
            str(row[1])
            for row in db.execute("PRAGMA index_list(object_index)")
        }
        assert "idx_object_graph_node" in indexes
        assert "idx_object_graph_attempt" in indexes
        # Existing projection rows remain readable after in-place convergence.
        assert db.execute(
            "SELECT object_id FROM object_index WHERE object_id='old-object'"
        ).fetchone() == ("old-object",)



def test_related_to_uses_exact_correlation_indexes_without_temp_sort(tmp_path) -> None:
    db = _db(tmp_path)
    with db.connect() as conn:
        plan = tuple(
            str(row[3])
            for row in conn.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT object_id, timestamp FROM object_index "
                "WHERE run_id IS ? AND trace_id=? "
                "ORDER BY timestamp, object_id LIMIT ?",
                ("run", "trace", 100),
            )
        )
    assert any("idx_object_related_trace" in row for row in plan)
    assert not any("TEMP B-TREE" in row for row in plan)


def test_related_to_merges_fixed_index_branches_and_deduplicates(tmp_path) -> None:
    db = _db(tmp_path)
    rows = (
        ("root", "run", "task", "trace", "span", 3.0),
        ("task-only", "run", "task", None, None, 1.0),
        ("trace-only", "run", None, "trace", None, 2.0),
        ("duplicate-keys", "run", "task", "trace", "span", 2.5),
        ("other-run", "other", "task", "trace", "span", 0.5),
    )
    with db.connect() as conn:
        for object_id, run_id, task_id, trace_id, span_id, timestamp in rows:
            conn.execute(
                "INSERT INTO object_index("
                "object_id,kind,run_id,task_id,decision_cycle_id,trace_id,"
                "span_id,component_id,timestamp,payload_json"
                ") VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    object_id,
                    "event",
                    run_id,
                    task_id,
                    None,
                    trace_id,
                    span_id,
                    "component",
                    timestamp,
                    json.dumps({"event_id": object_id}),
                ),
            )
        conn.commit()

    related = ForensicIndexReader(db).related_to("root", limit=10)
    assert tuple(row.object_id for row in related) == (
        "task-only",
        "trace-only",
        "duplicate-keys",
        "root",
    )


def test_related_to_complexity_contract_is_output_sensitive() -> None:
    from noetrium_platform.infrastructure.reliability.forensics.providers.index_queries import (
        RELATED_OBJECT_QUERY_COMPLEXITY,
    )

    contract = RELATED_OBJECT_QUERY_COMPLEXITY
    assert set(contract.time_upper_bound.variables) == {
        "indexed_objects",
        "related_limit",
    }
    assert contract.space_upper_bound == ComplexityBound.linear("related_limit")
