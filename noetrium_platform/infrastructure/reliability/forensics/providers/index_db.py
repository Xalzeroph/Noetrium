from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3


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
    timestamp REAL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_object_run_time ON object_index(run_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_object_task ON object_index(task_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_object_dc ON object_index(decision_cycle_id, timestamp);
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
            uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
            db = sqlite3.connect(uri, uri=True, timeout=30)
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA busy_timeout=30000")
            return db
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def initialize(self) -> None:
        if self.read_only:
            raise PermissionError("read-only forensic index cannot initialize schema")
        with closing(self.connect()) as db:
            with db:
                db.executescript(_SCHEMA)
