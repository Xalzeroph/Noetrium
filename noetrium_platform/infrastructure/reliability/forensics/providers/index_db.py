from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    SQLiteDurabilityProfile,
    open_durable_sqlite_reader,
    open_durable_sqlite_writer,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS object_index(
    object_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    run_id TEXT,
    task_id TEXT,
    decision_cycle_id TEXT,
    trace_id TEXT,
    span_id TEXT,
    component_id TEXT,
    research_revision_digest TEXT,
    research_execution_id TEXT,
    research_cut_id TEXT,
    graph_node_id TEXT,
    graph_attempt_id TEXT,
    graph_generation INTEGER,
    timestamp REAL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_object_run_time ON object_index(run_id, timestamp);
CREATE TABLE IF NOT EXISTS state_writers(
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
CREATE INDEX IF NOT EXISTS idx_state_writer ON state_writers(run_id, state_name, timestamp DESC);
CREATE TABLE IF NOT EXISTS operation_invocations(
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
CREATE INDEX IF NOT EXISTS idx_operation_invocation_run_started
    ON operation_invocations(run_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_operation_invocation_unclosed
    ON operation_invocations(run_id, terminal_at, started_at DESC);
CREATE TABLE IF NOT EXISTS ledger_freshness(
    ledger TEXT PRIMARY KEY,
    rows INTEGER NOT NULL,
    tail_hash TEXT NOT NULL
);
"""

_POST_OBJECT_MIGRATION_SCHEMA = """
-- Historical correlation indexes lacked run_id and therefore could not bound
-- related-object diagnostics to the exact execution partition.  The projection
-- is disposable, so converge rather than carrying both index families.
DROP INDEX IF EXISTS idx_object_task;
DROP INDEX IF EXISTS idx_object_dc;
CREATE INDEX IF NOT EXISTS idx_object_graph_node
    ON object_index(graph_node_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_object_graph_attempt
    ON object_index(graph_attempt_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_object_related_task
    ON object_index(run_id, task_id, timestamp, object_id);
CREATE INDEX IF NOT EXISTS idx_object_related_dc
    ON object_index(run_id, decision_cycle_id, timestamp, object_id);
CREATE INDEX IF NOT EXISTS idx_object_related_trace
    ON object_index(run_id, trace_id, timestamp, object_id);
CREATE INDEX IF NOT EXISTS idx_object_related_span
    ON object_index(run_id, span_id, timestamp, object_id);
CREATE INDEX IF NOT EXISTS idx_object_related_graph_node
    ON object_index(run_id, graph_node_id, timestamp, object_id);
CREATE INDEX IF NOT EXISTS idx_object_related_graph_attempt
    ON object_index(run_id, graph_attempt_id, timestamp, object_id);
CREATE INDEX IF NOT EXISTS idx_object_event_digest
    ON object_index(json_extract(payload_json, '$.event_digest'))
    WHERE json_valid(payload_json);
"""

_OBJECT_INDEX_CURRENT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("research_revision_digest", "TEXT"),
    ("research_execution_id", "TEXT"),
    ("research_cut_id", "TEXT"),
    ("graph_node_id", "TEXT"),
    ("graph_attempt_id", "TEXT"),
    ("graph_generation", "INTEGER"),
)


class ForensicIndexDB:
    """Connection/schema authority for the disposable SQLite projection."""

    def __init__(self, path: Path, *, read_only: bool) -> None:
        self.path = path
        self.read_only = read_only
        if read_only:
            if not path.exists():
                raise FileNotFoundError(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.initialize()

    def connect(self) -> sqlite3.Connection:
        if self.read_only:
            return open_durable_sqlite_reader(
                self.path,
                timeout_seconds=30.0,
            )
        return open_durable_sqlite_writer(
            self.path,
            timeout_seconds=30.0,
            profile=SQLiteDurabilityProfile.PROJECTION,
        )

    def connect_reader(self) -> sqlite3.Connection:
        return open_durable_sqlite_reader(
            self.path,
            timeout_seconds=30.0,
        )

    def initialize(self) -> None:
        if self.read_only:
            raise PermissionError("read-only forensic index cannot initialize schema")
        with closing(self.connect()) as db:
            with db:
                # Create base tables and legacy-independent indexes first.
                # Graph/research indexes are intentionally deferred until the
                # current object_index columns have been converged.
                db.executescript(_SCHEMA)
                columns = {
                    str(row[1])
                    for row in db.execute(
                        "PRAGMA table_info(object_index)"
                    ).fetchall()
                }
                for name, sql_type in _OBJECT_INDEX_CURRENT_COLUMNS:
                    if name in columns:
                        continue
                    db.execute(
                        f"ALTER TABLE object_index ADD COLUMN {name} {sql_type}"
                    )
                db.executescript(_POST_OBJECT_MIGRATION_SCHEMA)
