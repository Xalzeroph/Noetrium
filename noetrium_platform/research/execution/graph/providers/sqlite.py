from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from threading import Condition, get_ident
from time import monotonic
from uuid import uuid4

from noetrium_platform.foundation.kernel.event import (
    causal_event,
    causal_topological_order,
    event_field,
    event_ref,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.foundation.kernel.truth import TruthModality
from noetrium_platform.foundation.kernel.unit import NoetriumUnit, UnitRef
from noetrium_platform.foundation.kernel.unit_codec import decode_unit, encode_unit
from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    DurableSQLiteReaderOwner,
    DurableSQLiteWriterOwner,
    immediate_sqlite_transaction,
    sqlite_read_snapshot,
)
_SQLITE_INT64_MAX = (1 << 63) - 1
_SQLITE_IN_BATCH = 900


class _PriorityWriterGate:
    """Reentrant writer admission with strict heartbeat preference.

    SQLite still has one physical writer. This gate prevents an unbounded stream
    of ordinary graph transactions from repeatedly barging ahead of a lease
    renewal that is already waiting for the writer. The current holder is never
    preempted; once it exits, queued priority work wins before new normal work.
    """

    def __init__(self) -> None:
        self._condition = Condition()
        self._owner_thread_id: int | None = None
        self._depth = 0
        self._priority_waiters = 0

    @contextmanager
    def enter(
        self,
        *,
        priority: bool = False,
        timeout_seconds: float | None = None,
    ):
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("research graph writer wait timeout must be non-negative")
        deadline = None if timeout_seconds is None else monotonic() + timeout_seconds
        thread_id = get_ident()
        with self._condition:
            if self._owner_thread_id == thread_id:
                self._depth += 1
            else:
                if priority:
                    self._priority_waiters += 1
                try:
                    while self._owner_thread_id is not None or (
                        not priority and self._priority_waiters > 0
                    ):
                        if deadline is None:
                            self._condition.wait()
                            continue
                        remaining = deadline - monotonic()
                        if remaining <= 0:
                            raise TimeoutError(
                                "research graph writer admission deadline expired"
                            )
                        self._condition.wait(remaining)
                    self._owner_thread_id = thread_id
                    self._depth = 1
                finally:
                    if priority:
                        self._priority_waiters -= 1
        try:
            yield
        finally:
            with self._condition:
                if self._owner_thread_id != thread_id or self._depth <= 0:
                    raise RuntimeError("research graph writer gate ownership corrupted")
                self._depth -= 1
                if self._depth == 0:
                    self._owner_thread_id = None
                    self._condition.notify_all()


from noetrium_platform.research.execution.graph.api import (
    execution_graph_digest,
    execution_graph_id,
    execution_graph_index,
    execution_graph_research_revision_digest,
    execution_vertex_semantic_digest,
    ResearchGraphActiveCutRef,
    ResearchGraphActiveExecutionSnapshot,
    ResearchGraphAttemptRecord,
    ResearchGraphAttemptState,
    ResearchGraphControlPhase,
    ResearchGraphControlRecord,
    ResearchGraphCutSwitchFence,
    ResearchGraphExecutionConflict,
    ResearchGraphExecutionNotFound,
    ResearchGraphExecutionSnapshot,
    ResearchGraphFailureProvenance,
    ResearchGraphLeaseRenewal,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeControlPhase,
    ResearchGraphNodeControlRecord,
    ResearchGraphNodeExecutionRecord,
    ResearchGraphReconciliationDisposition,
    ResearchGraphReuseRecord,
)


class SQLiteResearchGraphExecutionStore:
    """Crash-durable graph orchestration state with attempt and lease history.

    This store owns only graph scheduling progress. Scientific execution state,
    effects, evidence and provider state stay in their lower canonical authorities.
    """

    SCHEMA_VERSION = 5

    @classmethod
    def default_path(cls, root: str | Path) -> Path:
        """Physical authority identity derived from the exact store schema."""
        return Path(root) / f"graph.v{cls.SCHEMA_VERSION}.sqlite3"

    def __init__(self, path: str | Path, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("research graph SQLite timeout must be positive")
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = float(timeout_seconds)
        self._writer_gate = _PriorityWriterGate()
        self._writers = DurableSQLiteWriterOwner(
            self.path,
            timeout_seconds=self.timeout_seconds,
        )
        with self._writer_connection() as conn:
            self._ensure_schema(conn)
        self._readers = DurableSQLiteReaderOwner(
            self.path,
            timeout_seconds=self.timeout_seconds,
        )

    @contextmanager
    def _connection(self):
        """Fresh, coherent read-only WAL snapshot outside writer admission.

        Read projections never hold the exclusive writer gate. This keeps
        control-plane observations and forensic scans off the durable claim,
        heartbeat and graph-transition critical path, without weakening the
        per-statement/whole-snapshot consistency contract.
        """
        with self._readers.session() as conn:
            with sqlite_read_snapshot(conn):
                yield conn

    @contextmanager
    def _writer_connection(
        self,
        *,
        priority: bool = False,
        timeout_seconds: float | None = None,
    ):
        with self._writer_gate.enter(
            priority=priority,
            timeout_seconds=timeout_seconds,
        ):
            with self._writers.session() as conn:
                yield conn

    def close(self) -> None:
        with self._writer_gate.enter(priority=True):
            self._readers.close()
            self._writers.close()

    @contextmanager
    def _transaction(
        self,
        *,
        priority: bool = False,
        timeout_seconds: float | None = None,
    ):
        resolved_timeout = self.timeout_seconds
        if timeout_seconds is not None:
            if timeout_seconds <= 0:
                raise TimeoutError("research graph transaction deadline expired")
            resolved_timeout = min(resolved_timeout, float(timeout_seconds))
        deadline = monotonic() + resolved_timeout
        with self._writer_connection(
            priority=priority,
            timeout_seconds=resolved_timeout,
        ) as conn:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("research graph transaction deadline expired")
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=remaining,
                label="research graph",
            ):
                pending = conn.execute(
                    "SELECT 1 FROM research_graph_changes LIMIT 1"
                ).fetchone()
                if pending is not None:
                    raise RuntimeError(
                        "research execution change queue leaked across transactions"
                    )
                yield conn
                self._materialize_change_events_locked(conn)

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_graph_meta("
            "key TEXT PRIMARY KEY,value TEXT NOT NULL)"
        )
        existing_version = conn.execute(
            "SELECT value FROM research_graph_meta WHERE key='schema_version'"
        ).fetchone()
        if (
            existing_version is not None
            and int(existing_version[0]) != self.SCHEMA_VERSION
        ):
            raise RuntimeError(
                "unsupported SQLiteResearchGraphExecutionStore schema; "
                "automatic compatibility migration is forbidden"
            )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_graph_executions("
            "execution_id TEXT PRIMARY KEY,"
            "graph_id TEXT NOT NULL,"
            "graph_digest TEXT NOT NULL,"
            "research_revision_digest TEXT NOT NULL,"
            "generation INTEGER NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_graph_control("
            "execution_id TEXT PRIMARY KEY,"
            "phase TEXT NOT NULL,"
            "generation INTEGER NOT NULL,"
            "updated_at_ns INTEGER NOT NULL,"
            "FOREIGN KEY(execution_id) REFERENCES research_graph_executions(execution_id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_graph_node_control("
            "execution_id TEXT NOT NULL,"
            "node_id TEXT NOT NULL,"
            "phase TEXT NOT NULL,"
            "generation INTEGER NOT NULL,"
            "updated_at_ns INTEGER NOT NULL,"
            "PRIMARY KEY(execution_id,node_id),"
            "FOREIGN KEY(execution_id) REFERENCES research_graph_executions(execution_id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_graph_nodes("
            "execution_id TEXT NOT NULL,"
            "node_id TEXT NOT NULL,"
            "semantic_digest TEXT NOT NULL,"
            "state TEXT NOT NULL,"
            "attempt_number INTEGER NOT NULL,"
            "attempt_id TEXT,"
            "lease_owner_id TEXT,"
            "lease_expires_at_ns INTEGER,"
            "retry_not_before_ns INTEGER,"
            "failure_type TEXT,"
            "failure_message TEXT,"
            "failure_provenance_json TEXT,"
            "blockers_json TEXT NOT NULL,"
            "PRIMARY KEY(execution_id,node_id),"
            "FOREIGN KEY(execution_id) REFERENCES research_graph_executions(execution_id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_graph_attempts("
            "execution_id TEXT NOT NULL,"
            "node_id TEXT NOT NULL,"
            "attempt_number INTEGER NOT NULL,"
            "attempt_id TEXT NOT NULL UNIQUE,"
            "owner_id TEXT NOT NULL,"
            "state TEXT NOT NULL,"
            "claimed_at_ns INTEGER NOT NULL,"
            "lease_expires_at_ns INTEGER NOT NULL,"
            "started_at_ns INTEGER,"
            "finished_at_ns INTEGER,"
            "failure_type TEXT,"
            "failure_message TEXT,"
            "failure_provenance_json TEXT,"
            "PRIMARY KEY(execution_id,node_id,attempt_number),"
            "FOREIGN KEY(execution_id,node_id) "
            "REFERENCES research_graph_nodes(execution_id,node_id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_graph_reuse("
            "execution_id TEXT NOT NULL,"
            "node_id TEXT NOT NULL,"
            "source_execution_id TEXT NOT NULL,"
            "source_node_id TEXT NOT NULL,"
            "semantic_digest TEXT NOT NULL,"
            "proof_digest TEXT NOT NULL,"
            "created_at_ns INTEGER NOT NULL,"
            "PRIMARY KEY(execution_id,node_id),"
            "FOREIGN KEY(execution_id,node_id) "
            "REFERENCES research_graph_nodes(execution_id,node_id),"
            "FOREIGN KEY(source_execution_id,source_node_id) "
            "REFERENCES research_graph_nodes(execution_id,node_id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_graph_active_cuts("
            "logical_execution_id TEXT PRIMARY KEY,"
            "cut_id TEXT NOT NULL,"
            "research_revision_digest TEXT NOT NULL,"
            "graph_digest TEXT NOT NULL,"
            "generation INTEGER NOT NULL,"
            "FOREIGN KEY(cut_id) REFERENCES research_graph_executions(execution_id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_graph_events("
            "event_digest TEXT PRIMARY KEY,"
            "authority_domain TEXT NOT NULL,"
            "generation INTEGER NOT NULL CHECK(generation >= 1),"
            "entity_kind TEXT NOT NULL,"
            "key1 TEXT NOT NULL,"
            "key2 TEXT NOT NULL,"
            "key3 TEXT NOT NULL,"
            "payload BLOB NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_graph_events_domain "
            "ON research_graph_events(authority_domain,event_digest)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_graph_event_heads("
            "authority_domain TEXT PRIMARY KEY,"
            "event_digest TEXT NOT NULL,"
            "generation INTEGER NOT NULL CHECK(generation >= 1))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_graph_changes("
            "entity_kind TEXT NOT NULL,"
            "key1 TEXT NOT NULL,"
            "key2 TEXT NOT NULL DEFAULT '',"
            "key3 TEXT NOT NULL DEFAULT '',"
            "PRIMARY KEY(entity_kind,key1,key2,key3))"
        )
        trigger_specs = (
            ("execution", "research_graph_executions", "execution_id", None, None),
            ("control", "research_graph_control", "execution_id", None, None),
            ("node-control", "research_graph_node_control", "execution_id", "node_id", None),
            ("node", "research_graph_nodes", "execution_id", "node_id", None),
            ("attempt", "research_graph_attempts", "execution_id", "node_id", "attempt_number"),
            ("reuse", "research_graph_reuse", "execution_id", "node_id", None),
            ("active-cut", "research_graph_active_cuts", "logical_execution_id", None, None),
        )
        for kind, table, key1, key2, key3 in trigger_specs:
            for operation, row_alias in (
                ("insert", "NEW"),
                ("update", "NEW"),
                ("delete", "OLD"),
            ):
                trigger_name = "trg_" + table + "_" + operation + "_event"
                key2_expr = "''" if key2 is None else f"CAST({row_alias}.{key2} AS TEXT)"
                key3_expr = "''" if key3 is None else f"CAST({row_alias}.{key3} AS TEXT)"
                conn.execute(
                    f"CREATE TRIGGER IF NOT EXISTS {trigger_name} "
                    f"AFTER {operation.upper()} ON {table} BEGIN "
                    "INSERT OR REPLACE INTO research_graph_changes"
                    "(entity_kind,key1,key2,key3) VALUES("
                    f"'{kind}',CAST({row_alias}.{key1} AS TEXT),"
                    f"{key2_expr},{key3_expr}); END"
                )
        conn.execute(
            "INSERT OR IGNORE INTO research_graph_meta(key,value) "
            "VALUES('schema_version',?)",
            (str(self.SCHEMA_VERSION),),
        )
        row = conn.execute(
            "SELECT value FROM research_graph_meta WHERE key='schema_version'"
        ).fetchone()
        if row is None or int(row[0]) != self.SCHEMA_VERSION:
            raise RuntimeError("unsupported SQLiteResearchGraphExecutionStore schema")

    @classmethod
    def _projection_rows_locked(
        cls,
        conn: sqlite3.Connection,
        changes: tuple[tuple[str, str, str, str], ...],
    ) -> dict[tuple[str, str, str, str], tuple[object, ...] | None]:
        """Fetch a complete change projection with bounded batched SQL.

        Runtime is linear in changed entities plus returned rows. Database
        round-trips grow with entity kinds and SQLite-sized chunks, never with
        individual changes.
        """

        supported = {
            "execution",
            "control",
            "node-control",
            "node",
            "attempt",
            "reuse",
            "active-cut",
        }
        unknown = tuple(
            sorted({change[0] for change in changes}.difference(supported))
        )
        if unknown:
            raise ValueError(
                "unknown research execution projection entities: "
                + ", ".join(unknown)
            )

        rows: dict[
            tuple[str, str, str, str],
            tuple[object, ...] | None,
        ] = {change: None for change in changes}
        by_kind: dict[str, list[tuple[str, str, str, str]]] = {
            kind: [] for kind in supported
        }
        for change in changes:
            by_kind[change[0]].append(change)

        for entity_kind, select_columns, table, key_column in (
            (
                "execution",
                "execution_id,graph_id,graph_digest,"
                "research_revision_digest,generation",
                "research_graph_executions",
                "execution_id",
            ),
            (
                "control",
                "execution_id,phase,generation,updated_at_ns",
                "research_graph_control",
                "execution_id",
            ),
            (
                "active-cut",
                "logical_execution_id,cut_id,research_revision_digest,"
                "graph_digest,generation",
                "research_graph_active_cuts",
                "logical_execution_id",
            ),
        ):
            keys = tuple(
                dict.fromkeys(change[1] for change in by_kind[entity_kind])
            )
            for start in range(0, len(keys), _SQLITE_IN_BATCH):
                batch = keys[start : start + _SQLITE_IN_BATCH]
                placeholders = ",".join("?" for _ in batch)
                fetched = conn.execute(
                    f"SELECT {select_columns} FROM {table} "
                    f"WHERE {key_column} IN ({placeholders})",
                    batch,
                ).fetchall()
                for row in fetched:
                    rows[(entity_kind, str(row[0]), "", "")] = tuple(row)

        pair_batch_size = max(1, _SQLITE_IN_BATCH // 2)
        for entity_kind, select_columns, table in (
            (
                "node",
                "t.execution_id,t.node_id,t.semantic_digest,t.state,"
                "t.attempt_number,t.attempt_id,t.lease_owner_id,"
                "t.lease_expires_at_ns,t.retry_not_before_ns,"
                "t.failure_type,t.failure_message,t.failure_provenance_json,"
                "t.blockers_json",
                "research_graph_nodes",
            ),
            (
                "node-control",
                "t.execution_id,t.node_id,t.phase,t.generation,t.updated_at_ns",
                "research_graph_node_control",
            ),
            (
                "reuse",
                "t.execution_id,t.node_id,t.source_execution_id,"
                "t.source_node_id,t.semantic_digest,t.proof_digest,"
                "t.created_at_ns",
                "research_graph_reuse",
            ),
        ):
            requested = tuple(
                dict.fromkeys(
                    (execution_id, node_id)
                    for _kind, execution_id, node_id, _key3
                    in by_kind[entity_kind]
                )
            )
            for start in range(0, len(requested), pair_batch_size):
                batch = requested[start : start + pair_batch_size]
                values_sql = ",".join("(?,?)" for _ in batch)
                parameters = tuple(
                    value
                    for execution_id, node_id in batch
                    for value in (execution_id, node_id)
                )
                fetched = conn.execute(
                    "WITH requested(execution_id,node_id) AS (VALUES "
                    + values_sql
                    + f") SELECT {select_columns} FROM {table} AS t "
                    "JOIN requested AS r "
                    "ON r.execution_id=t.execution_id AND r.node_id=t.node_id",
                    parameters,
                ).fetchall()
                for row in fetched:
                    rows[
                        (
                            entity_kind,
                            str(row[0]),
                            str(row[1]),
                            "",
                        )
                    ] = tuple(row)

        attempt_changes = tuple(
            dict.fromkeys(
                (
                    execution_id,
                    node_id,
                    int(attempt_number),
                )
                for _kind, execution_id, node_id, attempt_number
                in by_kind["attempt"]
            )
        )
        attempt_batch_size = max(1, _SQLITE_IN_BATCH // 3)
        for start in range(0, len(attempt_changes), attempt_batch_size):
            batch = attempt_changes[start : start + attempt_batch_size]
            values_sql = ",".join("(?,?,?)" for _ in batch)
            parameters = tuple(
                value
                for execution_id, node_id, attempt_number in batch
                for value in (execution_id, node_id, attempt_number)
            )
            fetched = conn.execute(
                "WITH requested(execution_id,node_id,attempt_number) AS (VALUES "
                + values_sql
                + ") SELECT t.execution_id,t.node_id,t.attempt_number,"
                "t.attempt_id,t.owner_id,t.state,t.claimed_at_ns,"
                "t.lease_expires_at_ns,t.started_at_ns,t.finished_at_ns,"
                "t.failure_type,t.failure_message,t.failure_provenance_json "
                "FROM research_graph_attempts AS t JOIN requested AS r "
                "ON r.execution_id=t.execution_id "
                "AND r.node_id=t.node_id "
                "AND r.attempt_number=t.attempt_number",
                parameters,
            ).fetchall()
            for row in fetched:
                rows[
                    (
                        "attempt",
                        str(row[0]),
                        str(row[1]),
                        str(row[2]),
                    )
                ] = tuple(row)

        return rows

    @staticmethod
    def _projection_domain(
        entity_kind: str,
        key1: str,
    ) -> str:
        namespace = (
            "research.active-cut"
            if entity_kind == "active-cut"
            else "research.execution"
        )
        return namespace + "." + canonical_digest(key1)[:32]

    @classmethod
    def _projection_subject(
        cls,
        entity_kind: str,
        key1: str,
        key2: str,
        key3: str,
        row: tuple[object, ...] | None,
    ) -> NoetriumUnit:
        payload = {
            "kind": "research.execution-state",
            "entity_kind": entity_kind,
            "key1": key1,
            "key2": key2,
            "key3": key3,
            "present": row is not None,
            "row": () if row is None else tuple(row),
        }
        digest = canonical_digest(payload)
        return NoetriumUnit(
            "research-state:" + digest,
            schemas=("research.execution-state",),
            attributes=payload,
        )

    def _materialize_change_events_locked(
        self,
        conn: sqlite3.Connection,
    ) -> None:
        changes = conn.execute(
            "SELECT entity_kind,key1,key2,key3 "
            "FROM research_graph_changes "
            "ORDER BY entity_kind,key1,key2,key3"
        ).fetchall()
        if not changes:
            return

        normalized_changes = tuple(
            (
                str(raw_kind),
                str(raw_key1),
                str(raw_key2),
                str(raw_key3),
            )
            for raw_kind, raw_key1, raw_key2, raw_key3 in changes
        )
        projection_rows = self._projection_rows_locked(
            conn,
            normalized_changes,
        )

        # One authority domain can accumulate thousands of entity transitions in
        # one transaction. Prefetch all causal heads in bounded batches, advance
        # every domain chain in memory, then publish event rows with one
        # executemany. This preserves exact parent order while making SQLite
        # round-trips independent of the number of changed entities.
        domains = tuple(
            dict.fromkeys(
                self._projection_domain(entity_kind, key1)
                for entity_kind, key1, _key2, _key3 in normalized_changes
            )
        )
        heads: dict[str, tuple[str, int] | None] = {
            domain: None for domain in domains
        }
        for start in range(0, len(domains), _SQLITE_IN_BATCH):
            batch = domains[start : start + _SQLITE_IN_BATCH]
            placeholders = ",".join("?" for _ in batch)
            for domain, event_digest, generation in conn.execute(
                "SELECT authority_domain,event_digest,generation "
                "FROM research_graph_event_heads "
                f"WHERE authority_domain IN ({placeholders})",
                batch,
            ).fetchall():
                heads[str(domain)] = (str(event_digest), int(generation))

        dirty_heads: dict[str, tuple[str, int]] = {}
        event_rows: list[tuple[object, ...]] = []
        for entity_kind, key1, key2, key3 in normalized_changes:
            row = projection_rows[(entity_kind, key1, key2, key3)]
            subject = self._projection_subject(
                entity_kind,
                key1,
                key2,
                key3,
                row,
            )
            domain = self._projection_domain(entity_kind, key1)
            head = dirty_heads.get(domain, heads[domain])
            generation = 1 if head is None else int(head[1]) + 1
            parents = (
                ()
                if head is None
                else (UnitRef(("event:" + str(head[0]),)),)
            )
            entity_key = ":".join(
                value
                for value in (entity_kind, key1, key2, key3)
                if value
            )
            event = causal_event(
                authority_domain=domain,
                generation=generation,
                subject=subject,
                operation="project-state",
                phase="upsert" if row is not None else "delete",
                modality=TruthModality.AUTHORIZED,
                causal_parents=parents,
                reads=(f"research-state:{entity_key}",),
                writes=(f"research-state:{entity_key}",),
                event_kind="research.execution-transition",
            )
            event_rows.append(
                (
                    event.unit_digest,
                    domain,
                    generation,
                    entity_kind,
                    key1,
                    key2,
                    key3,
                    encode_unit(event),
                )
            )
            dirty_heads[domain] = (event.unit_digest, generation)

        conn.executemany(
            "INSERT INTO research_graph_events("
            "event_digest,authority_domain,generation,entity_kind,"
            "key1,key2,key3,payload) VALUES(?,?,?,?,?,?,?,?)",
            event_rows,
        )
        conn.executemany(
            "INSERT INTO research_graph_event_heads("
            "authority_domain,event_digest,generation) VALUES(?,?,?) "
            "ON CONFLICT(authority_domain) DO UPDATE SET "
            "event_digest=excluded.event_digest,"
            "generation=excluded.generation",
            (
                (domain, event_digest, generation)
                for domain, (event_digest, generation)
                in sorted(dirty_heads.items())
            ),
        )
        conn.execute("DELETE FROM research_graph_changes")

    def event_trace(
        self,
        *,
        execution_id: str | None = None,
        logical_execution_id: str | None = None,
    ) -> tuple[NoetriumUnit, ...]:
        if execution_id is not None and logical_execution_id is not None:
            raise ValueError(
                "research event trace accepts execution_id or logical_execution_id"
            )
        clause = ""
        params: tuple[str, ...] = ()
        if execution_id is not None:
            domain = self._projection_domain("execution", execution_id)
            clause = " WHERE authority_domain=?"
            params = (domain,)
        elif logical_execution_id is not None:
            domain = self._projection_domain(
                "active-cut",
                logical_execution_id,
            )
            clause = " WHERE authority_domain=?"
            params = (domain,)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT payload FROM research_graph_events"
                + clause
                + " ORDER BY authority_domain,generation",
                params,
            ).fetchall()
        return tuple(decode_unit(bytes(row[0])) for row in rows)

    @staticmethod
    def _event_projection_map(
        events: tuple[NoetriumUnit, ...],
    ) -> dict[tuple[str, str, str, str], tuple[object, ...]]:
        projected: dict[
            tuple[str, str, str, str],
            tuple[object, ...],
        ] = {}
        if not events:
            return projected
        for event in causal_topological_order(events):
            subject = event_field(event, "subject")
            if (
                type(subject) is not NoetriumUnit
                or not subject.has_schema("research.execution-state")
            ):
                raise RuntimeError(
                    "research execution Journal contains invalid subject"
                )
            key = (
                str(subject.attribute("entity_kind")),
                str(subject.attribute("key1")),
                str(subject.attribute("key2")),
                str(subject.attribute("key3")),
            )
            if bool(subject.attribute("present")):
                row = subject.attribute("row")
                if type(row) is not tuple:
                    raise RuntimeError(
                        "research execution state row must be a tuple"
                    )
                projected[key] = tuple(row)
            else:
                projected.pop(key, None)
        return projected

    @classmethod
    def _materialized_projection_map_locked(
        cls,
        conn: sqlite3.Connection,
    ) -> dict[tuple[str, str, str, str], tuple[object, ...]]:
        result: dict[
            tuple[str, str, str, str],
            tuple[object, ...],
        ] = {}
        specs = (
            (
                "execution",
                "SELECT execution_id,graph_id,graph_digest,"
                "research_revision_digest,generation "
                "FROM research_graph_executions ORDER BY execution_id",
                lambda row: (str(row[0]), "", ""),
            ),
            (
                "control",
                "SELECT execution_id,phase,generation,updated_at_ns "
                "FROM research_graph_control ORDER BY execution_id",
                lambda row: (str(row[0]), "", ""),
            ),
            (
                "node-control",
                "SELECT execution_id,node_id,phase,generation,updated_at_ns "
                "FROM research_graph_node_control "
                "ORDER BY execution_id,node_id",
                lambda row: (str(row[0]), str(row[1]), ""),
            ),
            (
                "node",
                "SELECT execution_id,node_id,semantic_digest,state,"
                "attempt_number,attempt_id,lease_owner_id,"
                "lease_expires_at_ns,retry_not_before_ns,failure_type,"
                "failure_message,failure_provenance_json,blockers_json "
                "FROM research_graph_nodes ORDER BY execution_id,node_id",
                lambda row: (str(row[0]), str(row[1]), ""),
            ),
            (
                "attempt",
                "SELECT execution_id,node_id,attempt_number,attempt_id,"
                "owner_id,state,claimed_at_ns,lease_expires_at_ns,"
                "started_at_ns,finished_at_ns,failure_type,failure_message,"
                "failure_provenance_json FROM research_graph_attempts "
                "ORDER BY execution_id,node_id,attempt_number",
                lambda row: (
                    str(row[0]),
                    str(row[1]),
                    str(row[2]),
                ),
            ),
            (
                "reuse",
                "SELECT execution_id,node_id,source_execution_id,"
                "source_node_id,semantic_digest,proof_digest,created_at_ns "
                "FROM research_graph_reuse ORDER BY execution_id,node_id",
                lambda row: (str(row[0]), str(row[1]), ""),
            ),
            (
                "active-cut",
                "SELECT logical_execution_id,cut_id,"
                "research_revision_digest,graph_digest,generation "
                "FROM research_graph_active_cuts "
                "ORDER BY logical_execution_id",
                lambda row: (str(row[0]), "", ""),
            ),
        )
        for kind, sql, key_fn in specs:
            for row in conn.execute(sql).fetchall():
                key1, key2, key3 = key_fn(row)
                result[(kind, key1, key2, key3)] = tuple(row)
        return result

    def verify_projection_rebuild(self) -> None:
        events = self.event_trace()
        projected = self._event_projection_map(events)
        with self._connection() as conn:
            materialized = self._materialized_projection_map_locked(conn)
        if projected != materialized:
            missing = tuple(sorted(set(materialized) - set(projected)))
            extra = tuple(sorted(set(projected) - set(materialized)))
            differing = tuple(
                sorted(
                    key
                    for key in set(projected) & set(materialized)
                    if projected[key] != materialized[key]
                )
            )
            raise RuntimeError(
                "research execution projection diverged from Unit/Event Journal: "
                f"missing={missing[:8]} extra={extra[:8]} "
                f"differing={differing[:8]}"
            )

    @staticmethod
    def _decode_blockers(raw: object) -> tuple[str, ...]:
        values = json.loads(str(raw))
        if not isinstance(values, list) or any(type(value) is not str for value in values):
            raise RuntimeError("research graph blockers are corrupt")
        return tuple(values)

    @staticmethod
    def _encode_failure_provenance(
        provenance: ResearchGraphFailureProvenance,
    ) -> str:
        if not isinstance(provenance, ResearchGraphFailureProvenance):
            raise TypeError("research graph failure provenance must be typed")
        return json.dumps(
            provenance.as_payload(),
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _decode_failure_provenance(
        raw: object,
    ) -> ResearchGraphFailureProvenance | None:
        if raw is None:
            return None
        value = json.loads(str(raw))
        if not isinstance(value, dict):
            raise RuntimeError("research graph failure provenance is corrupt")
        provenance = ResearchGraphFailureProvenance(
            qualified_type=str(value["qualified_type"]),
            error_digest=str(value["error_digest"]),
            safe_message=str(value["safe_message"]),
            traceback_frames=tuple(
                str(row) for row in value.get("traceback_frames", ())
            ),
            cause_chain=tuple(str(row) for row in value.get("cause_chain", ())),
            failure_id=(
                None
                if value.get("failure_id") is None
                else str(value["failure_id"])
            ),
            evidence_refs=tuple(
                str(row) for row in value.get("evidence_refs", ())
            ),
            lower_refs=tuple(str(row) for row in value.get("lower_refs", ())),
        )
        expected = value.get("provenance_digest")
        if expected is not None and str(expected) != provenance.provenance_digest:
            raise RuntimeError(
                "research graph failure provenance digest mismatch"
            )
        return provenance

    @classmethod
    def _decode_node(cls, row: tuple[object, ...]) -> ResearchGraphNodeExecutionRecord:
        return ResearchGraphNodeExecutionRecord(
            execution_id=str(row[0]),
            node_id=str(row[1]),
            semantic_digest=str(row[2]),
            state=ResearchGraphLiveNodeState(str(row[3])),
            attempt_number=int(row[4]),
            attempt_id=None if row[5] is None else str(row[5]),
            lease_owner_id=None if row[6] is None else str(row[6]),
            lease_expires_at_ns=None if row[7] is None else int(row[7]),
            retry_not_before_ns=None if row[8] is None else int(row[8]),
            failure_type=None if row[9] is None else str(row[9]),
            failure_message=None if row[10] is None else str(row[10]),
            failure_provenance=cls._decode_failure_provenance(row[11]),
            blocked_by_node_ids=cls._decode_blockers(row[12]),
        )

    @staticmethod
    def _decode_attempt(row: tuple[object, ...]) -> ResearchGraphAttemptRecord:
        return ResearchGraphAttemptRecord(
            execution_id=str(row[0]),
            node_id=str(row[1]),
            attempt_number=int(row[2]),
            attempt_id=str(row[3]),
            owner_id=str(row[4]),
            state=ResearchGraphAttemptState(str(row[5])),
            claimed_at_ns=int(row[6]),
            lease_expires_at_ns=int(row[7]),
            started_at_ns=None if row[8] is None else int(row[8]),
            finished_at_ns=None if row[9] is None else int(row[9]),
            failure_type=None if row[10] is None else str(row[10]),
            failure_message=None if row[11] is None else str(row[11]),
            failure_provenance=SQLiteResearchGraphExecutionStore._decode_failure_provenance(
                row[12]
            ),
        )

    @staticmethod
    def _decode_reuse(row: tuple[object, ...]) -> ResearchGraphReuseRecord:
        return ResearchGraphReuseRecord(
            execution_id=str(row[0]),
            node_id=str(row[1]),
            source_execution_id=str(row[2]),
            source_node_id=str(row[3]),
            semantic_digest=str(row[4]),
            proof_digest=str(row[5]),
            created_at_ns=int(row[6]),
        )

    @staticmethod
    def _decode_node_control(row: tuple[object, ...]) -> ResearchGraphNodeControlRecord:
        return ResearchGraphNodeControlRecord(
            execution_id=str(row[0]),
            node_id=str(row[1]),
            phase=ResearchGraphNodeControlPhase(str(row[2])),
            generation=int(row[3]),
            updated_at_ns=int(row[4]),
        )

    @staticmethod
    def _decode_control(row: tuple[object, ...]) -> ResearchGraphControlRecord:
        return ResearchGraphControlRecord(
            execution_id=str(row[0]),
            phase=ResearchGraphControlPhase(str(row[1])),
            generation=int(row[2]),
            updated_at_ns=int(row[3]),
        )

    def _control_tx(
        self,
        conn: sqlite3.Connection,
        execution_id: str,
    ) -> ResearchGraphControlRecord:
        row = conn.execute(
            "SELECT execution_id,phase,generation,updated_at_ns "
            "FROM research_graph_control WHERE execution_id=?",
            (execution_id,),
        ).fetchone()
        if row is None:
            raise ResearchGraphExecutionNotFound(
                f"{execution_id}:control"
            )
        return self._decode_control(row)

    def _node_control_tx(
        self,
        conn: sqlite3.Connection,
        execution_id: str,
        node_id: str,
    ) -> ResearchGraphNodeControlRecord:
        row = conn.execute(
            "SELECT execution_id,node_id,phase,generation,updated_at_ns "
            "FROM research_graph_node_control WHERE execution_id=? AND node_id=?",
            (execution_id, node_id),
        ).fetchone()
        if row is None:
            raise ResearchGraphExecutionNotFound(
                f"{execution_id}:{node_id}:control"
            )
        return self._decode_node_control(row)

    @staticmethod
    def _write_node_control_phase_tx(
        conn: sqlite3.Connection,
        execution_id: str,
        node_id: str,
        *,
        expected_generation: int,
        phase: ResearchGraphNodeControlPhase,
        now_ns: int,
    ) -> None:
        updated = conn.execute(
            "UPDATE research_graph_node_control "
            "SET phase=?,generation=generation+1,updated_at_ns=? "
            "WHERE execution_id=? AND node_id=? AND generation=?",
            (
                phase.value,
                now_ns,
                execution_id,
                node_id,
                expected_generation,
            ),
        )
        if updated.rowcount != 1:
            raise ResearchGraphExecutionConflict(
                "research graph node control compare-and-swap conflict"
            )

    @staticmethod
    def _active_node_rows_tx(
        conn: sqlite3.Connection,
        execution_id: str,
    ) -> tuple[tuple[object, ...], ...]:
        rows = conn.execute(
            "SELECT node_id,state,attempt_id FROM research_graph_nodes "
            "WHERE execution_id=? AND state IN (?,?) ORDER BY node_id",
            (
                execution_id,
                ResearchGraphLiveNodeState.CLAIMED.value,
                ResearchGraphLiveNodeState.RUNNING.value,
            ),
        ).fetchall()
        return tuple(rows)

    @staticmethod
    def _reconciliation_node_ids_tx(
        conn: sqlite3.Connection,
        execution_id: str,
    ) -> tuple[str, ...]:
        rows = conn.execute(
            "SELECT node_id FROM research_graph_nodes "
            "WHERE execution_id=? AND state=? ORDER BY node_id",
            (
                execution_id,
                ResearchGraphLiveNodeState.RECONCILE_REQUIRED.value,
            ),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    @staticmethod
    def _write_control_phase_tx(
        conn: sqlite3.Connection,
        execution_id: str,
        *,
        expected_generation: int,
        phase: ResearchGraphControlPhase,
        now_ns: int,
    ) -> None:
        updated = conn.execute(
            "UPDATE research_graph_control "
            "SET phase=?,generation=generation+1,updated_at_ns=? "
            "WHERE execution_id=? AND generation=?",
            (
                phase.value,
                now_ns,
                execution_id,
                expected_generation,
            ),
        )
        if updated.rowcount != 1:
            raise ResearchGraphExecutionConflict(
                "research graph control compare-and-swap conflict"
            )

    @staticmethod
    def _decode_active_cut(row: tuple[object, ...]) -> ResearchGraphActiveCutRef:
        return ResearchGraphActiveCutRef(
            logical_execution_id=str(row[0]),
            cut_id=str(row[1]),
            research_revision_digest=str(row[2]),
            graph_digest=str(row[3]),
            generation=int(row[4]),
        )

    def _active_cut_tx(
        self,
        conn: sqlite3.Connection,
        logical_execution_id: str,
    ) -> ResearchGraphActiveCutRef | None:
        row = conn.execute(
            "SELECT logical_execution_id,cut_id,research_revision_digest,"
            "graph_digest,generation FROM research_graph_active_cuts "
            "WHERE logical_execution_id=?",
            (logical_execution_id,),
        ).fetchone()
        return None if row is None else self._decode_active_cut(row)

    def _execution_tx(
        self,
        conn: sqlite3.Connection,
        execution_id: str,
    ) -> tuple[object, ...]:
        row = conn.execute(
            "SELECT execution_id,graph_id,graph_digest,research_revision_digest,generation "
            "FROM research_graph_executions WHERE execution_id=?",
            (execution_id,),
        ).fetchone()
        if row is None:
            raise ResearchGraphExecutionNotFound(execution_id)
        return row

    def _node_tx(
        self,
        conn: sqlite3.Connection,
        execution_id: str,
        node_id: str,
    ) -> ResearchGraphNodeExecutionRecord:
        row = conn.execute(
            "SELECT execution_id,node_id,semantic_digest,state,attempt_number,"
            "attempt_id,lease_owner_id,lease_expires_at_ns,retry_not_before_ns,"
            "failure_type,failure_message,failure_provenance_json,blockers_json "
            "FROM research_graph_nodes WHERE execution_id=? AND node_id=?",
            (execution_id, node_id),
        ).fetchone()
        if row is None:
            raise ResearchGraphExecutionNotFound(f"{execution_id}:{node_id}")
        return self._decode_node(row)

    def _nodes_tx(
        self,
        conn: sqlite3.Connection,
        execution_id: str,
        node_ids: tuple[str, ...],
    ) -> tuple[ResearchGraphNodeExecutionRecord, ...]:
        """Read one already-canonical node set without re-sorting it.

        All callers cross the canonicalization boundary exactly once before
        entering this transaction helper. Strict adjacent ordering proves both
        lexical canonicality and uniqueness in Theta(N), avoiding a second
        comparison sort on every internal batch read.
        """
        if not node_ids:
            return ()
        if any(
            previous >= current
            for previous, current in zip(node_ids, node_ids[1:])
        ):
            raise ValueError(
                "research graph internal node batch ids must be canonical and unique"
            )
        ordered_ids = node_ids
        rows: list[tuple[object, ...]] = []
        for offset in range(0, len(ordered_ids), _SQLITE_IN_BATCH):
            batch = ordered_ids[offset : offset + _SQLITE_IN_BATCH]
            placeholders = ",".join("?" for _ in batch)
            rows.extend(
                conn.execute(
                    "SELECT execution_id,node_id,semantic_digest,state,attempt_number,"
                    "attempt_id,lease_owner_id,lease_expires_at_ns,retry_not_before_ns,"
                    "failure_type,failure_message,failure_provenance_json,blockers_json "
                    "FROM research_graph_nodes WHERE execution_id=? "
                    f"AND node_id IN ({placeholders}) ORDER BY node_id",
                    (execution_id, *batch),
                ).fetchall()
            )
        records = tuple(self._decode_node(row) for row in rows)
        actual_ids = tuple(row.node_id for row in records)
        if actual_ids != ordered_ids:
            missing = tuple(sorted(set(ordered_ids) - set(actual_ids)))
            raise ResearchGraphExecutionNotFound(
                f"research graph node batch missing nodes: {missing}"
            )
        return records

    def _snapshot_tx(
        self,
        conn: sqlite3.Connection,
        execution_id: str,
    ) -> ResearchGraphExecutionSnapshot:
        execution = self._execution_tx(conn, execution_id)
        rows = conn.execute(
            "SELECT execution_id,node_id,semantic_digest,state,attempt_number,"
            "attempt_id,lease_owner_id,lease_expires_at_ns,retry_not_before_ns,"
            "failure_type,failure_message,failure_provenance_json,blockers_json "
            "FROM research_graph_nodes WHERE execution_id=? ORDER BY node_id",
            (execution_id,),
        ).fetchall()
        return ResearchGraphExecutionSnapshot(
            execution_id=str(execution[0]),
            graph_id=str(execution[1]),
            graph_digest=str(execution[2]),
            research_revision_digest=str(execution[3]),
            generation=int(execution[4]),
            nodes=tuple(self._decode_node(row) for row in rows),
        )

    @staticmethod
    def _advance_generation(
        conn: sqlite3.Connection,
        execution_id: str,
        delta: int,
    ) -> None:
        if type(delta) is not int or delta < 1:
            raise ValueError("research graph generation delta must be positive")
        updated = conn.execute(
            "UPDATE research_graph_executions SET generation=generation+? "
            "WHERE execution_id=?",
            (delta, execution_id),
        )
        if updated.rowcount != 1:
            raise ResearchGraphExecutionNotFound(execution_id)

    @classmethod
    def _bump_generation(cls, conn: sqlite3.Connection, execution_id: str) -> None:
        cls._advance_generation(conn, execution_id, 1)

    @staticmethod
    def _require_timestamp_ns(value: int, field_name: str) -> int:
        if (
            type(value) is not int
            or value < 0
            or value > _SQLITE_INT64_MAX
        ):
            raise ValueError(
                f"{field_name} must be an unsigned nanosecond timestamp "
                "within SQLite signed 64-bit storage"
            )
        return value

    @classmethod
    def _require_now(cls, now_ns: int) -> int:
        return cls._require_timestamp_ns(now_ns, "research graph now_ns")

    def _ensure_execution_identity_tx(
        self,
        conn: sqlite3.Connection,
        execution_id: str,
        plan: NoetriumUnit,
    ) -> None:
        row = conn.execute(
            "SELECT graph_id,graph_digest,research_revision_digest "
            "FROM research_graph_executions WHERE execution_id=?",
            (execution_id,),
        ).fetchone()
        expected = (
            execution_graph_id(plan),
            execution_graph_digest(plan),
            execution_graph_research_revision_digest(plan),
        )
        if row is None:
            conn.execute(
                "INSERT INTO research_graph_executions("
                "execution_id,graph_id,graph_digest,research_revision_digest,generation"
                ") VALUES(?,?,?,?,1)",
                (execution_id, *expected),
            )
            conn.execute(
                "INSERT INTO research_graph_control("
                "execution_id,phase,generation,updated_at_ns"
                ") VALUES(?,?,1,0)",
                (execution_id, ResearchGraphControlPhase.ACTIVE.value),
            )
            return
        actual = (str(row[0]), str(row[1]), str(row[2]))
        if actual != expected:
            raise ResearchGraphExecutionConflict(
                "execution id is already bound to a different immutable NoetriumUnit"
            )
        control = conn.execute(
            "SELECT phase,generation FROM research_graph_control "
            "WHERE execution_id=?",
            (execution_id,),
        ).fetchone()
        if control is None:
            raise RuntimeError(
                "durable research graph execution lost control state"
            )

    def _materialize_nodes_tx(
        self,
        conn: sqlite3.Connection,
        execution_id: str,
        plan: NoetriumUnit,
        node_ids: tuple[str, ...],
    ) -> tuple[ResearchGraphNodeExecutionRecord, ...]:
        if type(node_ids) is not tuple or any(
            type(node_id) is not str or not node_id.strip()
            for node_id in node_ids
        ):
            raise TypeError(
                "research graph materialization ids must be a text tuple"
            )
        ordered_ids = tuple(sorted(node_ids))
        if len(ordered_ids) != len(set(ordered_ids)):
            raise ValueError(
                "research graph materialization ids must be unique"
            )
        if not ordered_ids:
            return ()
        try:
            index = execution_graph_index(plan)
            vertices = {
                node_id: index.by_id[node_id]
                for node_id in ordered_ids
            }
        except KeyError as exc:
            raise ValueError(
                "research graph materialization references unknown nodes"
            ) from exc
        conn.executemany(
            "INSERT OR IGNORE INTO research_graph_node_control("
            "execution_id,node_id,phase,generation,updated_at_ns"
            ") VALUES(?,?,?,1,0)",
            (
                (
                    execution_id,
                    node_id,
                    ResearchGraphNodeControlPhase.ACTIVE.value,
                )
                for node_id in ordered_ids
            ),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO research_graph_nodes("
            "execution_id,node_id,semantic_digest,state,attempt_number,"
            "blockers_json) VALUES(?,?,?,?,0,'[]')",
            (
                (
                    execution_id,
                    node_id,
                    execution_vertex_semantic_digest(vertices[node_id]),
                    ResearchGraphLiveNodeState.PENDING.value,
                )
                for node_id in ordered_ids
            ),
        )
        records = self._nodes_tx(conn, execution_id, ordered_ids)
        for record in records:
            expected_digest = execution_vertex_semantic_digest(
                vertices[record.node_id]
            )
            if record.semantic_digest != expected_digest:
                raise ResearchGraphExecutionConflict(
                    "durable graph node semantic identity differs from immutable plan"
                )
        return records

    def ensure_execution_identity(
        self,
        execution_id: str,
        plan: NoetriumUnit,
    ) -> ResearchGraphExecutionSnapshot:
        if type(execution_id) is not str or not execution_id.strip():
            raise ValueError("research graph execution_id must be non-empty")
        require_sha256(execution_graph_digest(plan), "research graph execution graph_digest")
        with self._transaction() as conn:
            self._ensure_execution_identity_tx(conn, execution_id, plan)
            return self._snapshot_tx(conn, execution_id)

    def materialize_nodes(
        self,
        execution_id: str,
        plan: NoetriumUnit,
        node_ids: tuple[str, ...],
    ) -> tuple[ResearchGraphNodeExecutionRecord, ...]:
        if type(execution_id) is not str or not execution_id.strip():
            raise ValueError("research graph execution_id must be non-empty")
        require_sha256(execution_graph_digest(plan), "research graph execution graph_digest")
        with self._transaction() as conn:
            self._ensure_execution_identity_tx(conn, execution_id, plan)
            return self._materialize_nodes_tx(
                conn, execution_id, plan, node_ids
            )

    def snapshot(self, execution_id: str) -> ResearchGraphExecutionSnapshot:
        with self._connection() as conn:
            return self._snapshot_tx(conn, execution_id)

    def node_state(
        self,
        execution_id: str,
        node_id: str,
    ) -> ResearchGraphNodeExecutionRecord:
        with self._connection() as conn:
            return self._node_tx(conn, execution_id, node_id)

    def node_states(
        self,
        execution_id: str,
        node_ids: tuple[str, ...],
    ) -> tuple[ResearchGraphNodeExecutionRecord, ...]:
        if type(node_ids) is not tuple or not node_ids or any(
            type(node_id) is not str or not node_id.strip()
            for node_id in node_ids
        ):
            raise TypeError(
                "research graph node_states requires a non-empty text tuple"
            )
        ordered_ids = tuple(sorted(node_ids))
        if len(ordered_ids) != len(set(ordered_ids)):
            raise ValueError("research graph node_states ids must be unique")
        with self._connection() as conn:
            return self._nodes_tx(conn, execution_id, ordered_ids)

    def control_state(
        self,
        execution_id: str,
    ) -> ResearchGraphControlRecord:
        with self._connection() as conn:
            return self._control_tx(conn, execution_id)

    def node_control_state(
        self,
        execution_id: str,
        node_id: str,
    ) -> ResearchGraphNodeControlRecord:
        with self._connection() as conn:
            self._node_tx(conn, execution_id, node_id)
            return self._node_control_tx(conn, execution_id, node_id)

    def node_control_snapshot(
        self,
        execution_id: str,
    ) -> tuple[ResearchGraphNodeControlRecord, ...]:
        with self._connection() as conn:
            self._execution_tx(conn, execution_id)
            rows = conn.execute(
                "SELECT execution_id,node_id,phase,generation,updated_at_ns "
                "FROM research_graph_node_control WHERE execution_id=? "
                "ORDER BY node_id",
                (execution_id,),
            ).fetchall()
        return tuple(self._decode_node_control(row) for row in rows)

    def node_control_states(
        self,
        execution_id: str,
        node_ids: tuple[str, ...],
    ) -> tuple[ResearchGraphNodeControlRecord, ...]:
        if type(node_ids) is not tuple or not node_ids or any(
            type(node_id) is not str or not node_id.strip()
            for node_id in node_ids
        ):
            raise TypeError(
                "research graph node_control_states requires a non-empty text tuple"
            )
        ordered_ids = tuple(sorted(node_ids))
        if len(ordered_ids) != len(set(ordered_ids)):
            raise ValueError(
                "research graph node_control_states ids must be unique"
            )
        rows: list[tuple[object, ...]] = []
        with self._connection() as conn:
            for offset in range(0, len(ordered_ids), _SQLITE_IN_BATCH):
                batch = ordered_ids[offset : offset + _SQLITE_IN_BATCH]
                placeholders = ",".join("?" for _ in batch)
                rows.extend(
                    conn.execute(
                        "SELECT execution_id,node_id,phase,generation,updated_at_ns "
                        "FROM research_graph_node_control WHERE execution_id=? "
                        f"AND node_id IN ({placeholders}) ORDER BY node_id",
                        (execution_id, *batch),
                    ).fetchall()
                )
        records = tuple(self._decode_node_control(row) for row in rows)
        actual_ids = tuple(row.node_id for row in records)
        if actual_ids != ordered_ids:
            missing = tuple(sorted(set(ordered_ids) - set(actual_ids)))
            raise ResearchGraphExecutionNotFound(
                f"research graph node_control_states missing nodes: {missing}"
            )
        return records

    def request_node_drain(
        self,
        execution_id: str,
        node_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphNodeControlRecord:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            self._node_tx(conn, execution_id, node_id)
            current = self._node_control_tx(conn, execution_id, node_id)
            if current.generation != expected_generation:
                raise ResearchGraphExecutionConflict(
                    "research graph node control compare-and-swap conflict"
                )
            if current.phase in {
                ResearchGraphNodeControlPhase.DRAINING,
                ResearchGraphNodeControlPhase.PAUSED,
            }:
                return current
            if current.phase is not ResearchGraphNodeControlPhase.ACTIVE:
                raise ResearchGraphExecutionConflict(
                    f"cannot drain node from control phase {current.phase.value}"
                )
            self._write_node_control_phase_tx(
                conn, execution_id, node_id,
                expected_generation=expected_generation,
                phase=ResearchGraphNodeControlPhase.DRAINING,
                now_ns=now_ns,
            )
            return self._node_control_tx(conn, execution_id, node_id)

    def pause_node_if_quiescent(
        self,
        execution_id: str,
        node_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphNodeControlRecord:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            node = self._node_tx(conn, execution_id, node_id)
            current = self._node_control_tx(conn, execution_id, node_id)
            if current.generation != expected_generation:
                raise ResearchGraphExecutionConflict(
                    "research graph node control compare-and-swap conflict"
                )
            if current.phase is ResearchGraphNodeControlPhase.PAUSED:
                return current
            if current.phase not in {
                ResearchGraphNodeControlPhase.ACTIVE,
                ResearchGraphNodeControlPhase.DRAINING,
            }:
                raise ResearchGraphExecutionConflict(
                    f"cannot pause node from control phase {current.phase.value}"
                )
            if node.state in {
                ResearchGraphLiveNodeState.CLAIMED,
                ResearchGraphLiveNodeState.RUNNING,
            }:
                raise ResearchGraphExecutionConflict(
                    "research graph node pause requires quiescence or prior interrupt"
                )
            if node.state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED:
                raise ResearchGraphExecutionConflict(
                    "research graph node pause is blocked by reconciliation debt"
                )
            if node.state is ResearchGraphLiveNodeState.CANCELLED:
                raise ResearchGraphExecutionConflict(
                    "cancelled graph node cannot be paused"
                )
            self._write_node_control_phase_tx(
                conn, execution_id, node_id,
                expected_generation=expected_generation,
                phase=ResearchGraphNodeControlPhase.PAUSED,
                now_ns=now_ns,
            )
            return self._node_control_tx(conn, execution_id, node_id)

    def resume_node(
        self,
        execution_id: str,
        node_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphNodeControlRecord:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            node = self._node_tx(conn, execution_id, node_id)
            current = self._node_control_tx(conn, execution_id, node_id)
            if current.generation != expected_generation:
                raise ResearchGraphExecutionConflict(
                    "research graph node control compare-and-swap conflict"
                )
            if current.phase is ResearchGraphNodeControlPhase.ACTIVE:
                return current
            if current.phase is not ResearchGraphNodeControlPhase.PAUSED:
                raise ResearchGraphExecutionConflict(
                    f"cannot resume node from control phase {current.phase.value}"
                )
            if node.state in {
                ResearchGraphLiveNodeState.SUCCEEDED,
                ResearchGraphLiveNodeState.REUSED,
                ResearchGraphLiveNodeState.FAILED,
                ResearchGraphLiveNodeState.CANCELLED,
                ResearchGraphLiveNodeState.RECONCILE_REQUIRED,
            }:
                raise ResearchGraphExecutionConflict(
                    "terminal or uncertain graph node cannot be resumed"
                )
            self._write_node_control_phase_tx(
                conn, execution_id, node_id,
                expected_generation=expected_generation,
                phase=ResearchGraphNodeControlPhase.ACTIVE,
                now_ns=now_ns,
            )
            return self._node_control_tx(conn, execution_id, node_id)

    def interrupt_node(
        self,
        execution_id: str,
        node_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphNodeControlRecord:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            node = self._node_tx(conn, execution_id, node_id)
            current = self._node_control_tx(conn, execution_id, node_id)
            if current.generation != expected_generation:
                raise ResearchGraphExecutionConflict(
                    "research graph node control compare-and-swap conflict"
                )
            if current.phase not in {
                ResearchGraphNodeControlPhase.ACTIVE,
                ResearchGraphNodeControlPhase.DRAINING,
            }:
                raise ResearchGraphExecutionConflict(
                    f"cannot interrupt node from control phase {current.phase.value}"
                )
            if node.state is ResearchGraphLiveNodeState.CLAIMED:
                if node.attempt_id is None:
                    raise RuntimeError("claimed graph node lost attempt identity")
                conn.execute(
                    "UPDATE research_graph_nodes SET state=?,attempt_id=NULL,"
                    "lease_owner_id=NULL,lease_expires_at_ns=NULL,retry_not_before_ns=NULL "
                    "WHERE execution_id=? AND node_id=?",
                    (ResearchGraphLiveNodeState.PENDING.value, execution_id, node_id),
                )
                conn.execute(
                    "UPDATE research_graph_attempts SET state=?,finished_at_ns=? "
                    "WHERE attempt_id=?",
                    (ResearchGraphAttemptState.EXPIRED_BEFORE_START.value, now_ns, node.attempt_id),
                )
                self._bump_generation(conn, execution_id)
                phase = ResearchGraphNodeControlPhase.PAUSED
            elif node.state is ResearchGraphLiveNodeState.RUNNING:
                if node.attempt_id is None:
                    raise RuntimeError("running graph node lost attempt identity")
                conn.execute(
                    "UPDATE research_graph_nodes SET state=?,lease_owner_id=NULL,"
                    "lease_expires_at_ns=NULL,retry_not_before_ns=NULL "
                    "WHERE execution_id=? AND node_id=?",
                    (ResearchGraphLiveNodeState.RECONCILE_REQUIRED.value, execution_id, node_id),
                )
                conn.execute(
                    "UPDATE research_graph_attempts SET state=?,finished_at_ns=? "
                    "WHERE attempt_id=?",
                    (ResearchGraphAttemptState.RECONCILE_REQUIRED.value, now_ns, node.attempt_id),
                )
                self._bump_generation(conn, execution_id)
                phase = ResearchGraphNodeControlPhase.RECOVERY_REQUIRED
            elif node.state in {
                ResearchGraphLiveNodeState.PENDING,
                ResearchGraphLiveNodeState.READY,
                ResearchGraphLiveNodeState.RETRY_WAIT,
            }:
                phase = ResearchGraphNodeControlPhase.PAUSED
            else:
                raise ResearchGraphExecutionConflict(
                    f"graph node state cannot be interrupted: {node.state.value}"
                )
            self._write_node_control_phase_tx(
                conn, execution_id, node_id,
                expected_generation=expected_generation,
                phase=phase,
                now_ns=now_ns,
            )
            return self._node_control_tx(conn, execution_id, node_id)

    def settle_node_recovery(
        self,
        execution_id: str,
        node_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphNodeControlRecord:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            node = self._node_tx(conn, execution_id, node_id)
            current = self._node_control_tx(conn, execution_id, node_id)
            if current.generation != expected_generation:
                raise ResearchGraphExecutionConflict(
                    "research graph node control compare-and-swap conflict"
                )
            if current.phase is ResearchGraphNodeControlPhase.PAUSED:
                return current
            if current.phase is not ResearchGraphNodeControlPhase.RECOVERY_REQUIRED:
                raise ResearchGraphExecutionConflict(
                    "node recovery settlement requires recovery_required control"
                )
            if node.state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED:
                raise ResearchGraphExecutionConflict(
                    "node recovery cannot settle before reconciliation completes"
                )
            self._write_node_control_phase_tx(
                conn, execution_id, node_id,
                expected_generation=expected_generation,
                phase=ResearchGraphNodeControlPhase.PAUSED,
                now_ns=now_ns,
            )
            return self._node_control_tx(conn, execution_id, node_id)

    def cancel_node_subgraph(
        self,
        execution_id: str,
        node_id: str,
        *,
        descendant_node_ids: tuple[str, ...],
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphNodeControlRecord:
        now_ns = self._require_now(now_ns)
        if type(descendant_node_ids) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in descendant_node_ids
        ):
            raise TypeError("cancel descendant_node_ids must be a text tuple")
        targets = tuple(sorted({node_id, *descendant_node_ids}))
        with self._transaction() as conn:
            root_control = self._node_control_tx(conn, execution_id, node_id)
            if root_control.generation != expected_generation:
                raise ResearchGraphExecutionConflict(
                    "research graph node control compare-and-swap conflict"
                )
            records = {
                target: self._node_tx(conn, execution_id, target)
                for target in targets
            }
            forbidden = tuple(
                sorted(
                    (target, record.state.value)
                    for target, record in records.items()
                    if record.state in {
                        ResearchGraphLiveNodeState.CLAIMED,
                        ResearchGraphLiveNodeState.RUNNING,
                        ResearchGraphLiveNodeState.RECONCILE_REQUIRED,
                        ResearchGraphLiveNodeState.SUCCEEDED,
                        ResearchGraphLiveNodeState.REUSED,
                        ResearchGraphLiveNodeState.FAILED,
                    }
                )
            )
            if forbidden:
                raise ResearchGraphExecutionConflict(
                    f"node subgraph cannot be cancelled from terminal/active states: {forbidden}"
                )
            for target in targets:
                control = self._node_control_tx(conn, execution_id, target)
                conn.execute(
                    "UPDATE research_graph_nodes SET state=?,attempt_id=NULL,"
                    "lease_owner_id=NULL,lease_expires_at_ns=NULL,retry_not_before_ns=NULL,"
                    "failure_type=NULL,failure_message=NULL,failure_provenance_json=NULL,blockers_json='[]' "
                    "WHERE execution_id=? AND node_id=?",
                    (ResearchGraphLiveNodeState.CANCELLED.value, execution_id, target),
                )
                self._write_node_control_phase_tx(
                    conn, execution_id, target,
                    expected_generation=control.generation,
                    phase=ResearchGraphNodeControlPhase.CANCELLED,
                    now_ns=now_ns,
                )
            self._bump_generation(conn, execution_id)
            return self._node_control_tx(conn, execution_id, node_id)

    def request_drain(
        self,
        execution_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphControlRecord:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            self._execution_tx(conn, execution_id)
            current = self._control_tx(conn, execution_id)
            if current.generation != expected_generation:
                raise ResearchGraphExecutionConflict(
                    "research graph control compare-and-swap conflict"
                )
            if current.phase in {
                ResearchGraphControlPhase.DRAINING,
                ResearchGraphControlPhase.PAUSED,
            }:
                return current
            if current.phase is not ResearchGraphControlPhase.ACTIVE:
                raise ResearchGraphExecutionConflict(
                    f"cannot drain graph from control phase {current.phase.value}"
                )
            self._write_control_phase_tx(
                conn,
                execution_id,
                expected_generation=expected_generation,
                phase=ResearchGraphControlPhase.DRAINING,
                now_ns=now_ns,
            )
            return self._control_tx(conn, execution_id)

    def pause_if_quiescent(
        self,
        execution_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphControlRecord:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            self._execution_tx(conn, execution_id)
            current = self._control_tx(conn, execution_id)
            if current.generation != expected_generation:
                raise ResearchGraphExecutionConflict(
                    "research graph control compare-and-swap conflict"
                )
            if current.phase is ResearchGraphControlPhase.PAUSED:
                return current
            if current.phase not in {
                ResearchGraphControlPhase.ACTIVE,
                ResearchGraphControlPhase.DRAINING,
            }:
                raise ResearchGraphExecutionConflict(
                    f"cannot pause graph from control phase {current.phase.value}"
                )
            active = self._active_node_rows_tx(conn, execution_id)
            if active:
                raise ResearchGraphExecutionConflict(
                    "research graph pause requires a quiescent cut; "
                    f"active_nodes={tuple(str(row[0]) for row in active)}"
                )
            debt = self._reconciliation_node_ids_tx(conn, execution_id)
            if debt:
                raise ResearchGraphExecutionConflict(
                    "research graph pause is blocked by reconciliation debt: "
                    f"{debt}"
                )
            self._write_control_phase_tx(
                conn,
                execution_id,
                expected_generation=expected_generation,
                phase=ResearchGraphControlPhase.PAUSED,
                now_ns=now_ns,
            )
            return self._control_tx(conn, execution_id)

    def resume(
        self,
        execution_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphControlRecord:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            self._execution_tx(conn, execution_id)
            current = self._control_tx(conn, execution_id)
            if current.generation != expected_generation:
                raise ResearchGraphExecutionConflict(
                    "research graph control compare-and-swap conflict"
                )
            if current.phase is ResearchGraphControlPhase.ACTIVE:
                return current
            if current.phase is not ResearchGraphControlPhase.PAUSED:
                raise ResearchGraphExecutionConflict(
                    f"cannot resume graph from control phase {current.phase.value}"
                )
            debt = self._reconciliation_node_ids_tx(conn, execution_id)
            if debt:
                raise ResearchGraphExecutionConflict(
                    "research graph resume is blocked by reconciliation debt: "
                    f"{debt}"
                )
            self._write_control_phase_tx(
                conn,
                execution_id,
                expected_generation=expected_generation,
                phase=ResearchGraphControlPhase.ACTIVE,
                now_ns=now_ns,
            )
            return self._control_tx(conn, execution_id)

    def interrupt(
        self,
        execution_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphControlRecord:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            self._execution_tx(conn, execution_id)
            current = self._control_tx(conn, execution_id)
            if current.generation != expected_generation:
                raise ResearchGraphExecutionConflict(
                    "research graph control compare-and-swap conflict"
                )
            if current.phase not in {
                ResearchGraphControlPhase.ACTIVE,
                ResearchGraphControlPhase.DRAINING,
            }:
                raise ResearchGraphExecutionConflict(
                    f"cannot interrupt graph from control phase {current.phase.value}"
                )
            active = self._active_node_rows_tx(conn, execution_id)
            recovery_required = False
            for node_id_raw, state_raw, attempt_id_raw in active:
                node_id = str(node_id_raw)
                state = ResearchGraphLiveNodeState(str(state_raw))
                attempt_id = None if attempt_id_raw is None else str(attempt_id_raw)
                if attempt_id is None:
                    raise RuntimeError(
                        "active research graph node lost attempt identity"
                    )
                if state is ResearchGraphLiveNodeState.CLAIMED:
                    conn.execute(
                        "UPDATE research_graph_nodes SET state=?,attempt_id=NULL,"
                        "lease_owner_id=NULL,lease_expires_at_ns=NULL,"
                        "retry_not_before_ns=NULL WHERE execution_id=? AND node_id=?",
                        (
                            ResearchGraphLiveNodeState.PENDING.value,
                            execution_id,
                            node_id,
                        ),
                    )
                    conn.execute(
                        "UPDATE research_graph_attempts SET state=?,finished_at_ns=? "
                        "WHERE attempt_id=?",
                        (
                            ResearchGraphAttemptState.EXPIRED_BEFORE_START.value,
                            now_ns,
                            attempt_id,
                        ),
                    )
                else:
                    recovery_required = True
                    conn.execute(
                        "UPDATE research_graph_nodes SET state=?,"
                        "lease_owner_id=NULL,lease_expires_at_ns=NULL,"
                        "retry_not_before_ns=NULL WHERE execution_id=? AND node_id=?",
                        (
                            ResearchGraphLiveNodeState.RECONCILE_REQUIRED.value,
                            execution_id,
                            node_id,
                        ),
                    )
                    conn.execute(
                        "UPDATE research_graph_attempts SET state=?,finished_at_ns=? "
                        "WHERE attempt_id=?",
                        (
                            ResearchGraphAttemptState.RECONCILE_REQUIRED.value,
                            now_ns,
                            attempt_id,
                        ),
                    )
            if active:
                self._bump_generation(conn, execution_id)
            target_phase = (
                ResearchGraphControlPhase.RECOVERY_REQUIRED
                if recovery_required
                else ResearchGraphControlPhase.PAUSED
            )
            self._write_control_phase_tx(
                conn,
                execution_id,
                expected_generation=expected_generation,
                phase=target_phase,
                now_ns=now_ns,
            )
            return self._control_tx(conn, execution_id)

    def cancel_if_quiescent(
        self,
        execution_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphControlRecord:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            self._execution_tx(conn, execution_id)
            current = self._control_tx(conn, execution_id)
            if current.generation != expected_generation:
                raise ResearchGraphExecutionConflict(
                    "research graph control compare-and-swap conflict"
                )
            if current.phase is ResearchGraphControlPhase.CANCELLED:
                return current
            active = self._active_node_rows_tx(conn, execution_id)
            if active:
                raise ResearchGraphExecutionConflict(
                    "research graph cancel requires quiescence or prior interrupt"
                )
            debt = self._reconciliation_node_ids_tx(conn, execution_id)
            if debt:
                raise ResearchGraphExecutionConflict(
                    "research graph cancel is blocked by reconciliation debt: "
                    f"{debt}"
                )
            self._write_control_phase_tx(
                conn,
                execution_id,
                expected_generation=expected_generation,
                phase=ResearchGraphControlPhase.CANCELLED,
                now_ns=now_ns,
            )
            return self._control_tx(conn, execution_id)

    def require_recovery(
        self,
        execution_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphControlRecord:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            self._execution_tx(conn, execution_id)
            current = self._control_tx(conn, execution_id)
            if current.generation != expected_generation:
                raise ResearchGraphExecutionConflict(
                    "research graph control compare-and-swap conflict"
                )
            if current.phase is ResearchGraphControlPhase.RECOVERY_REQUIRED:
                return current
            if current.phase not in {
                ResearchGraphControlPhase.ACTIVE,
                ResearchGraphControlPhase.DRAINING,
            }:
                raise ResearchGraphExecutionConflict(
                    "research graph recovery-required transition is invalid from "
                    f"{current.phase.value}"
                )
            debt = self._reconciliation_node_ids_tx(conn, execution_id)
            if not debt:
                raise ResearchGraphExecutionConflict(
                    "research graph cannot enter recovery_required without "
                    "reconciliation debt"
                )
            self._write_control_phase_tx(
                conn,
                execution_id,
                expected_generation=expected_generation,
                phase=ResearchGraphControlPhase.RECOVERY_REQUIRED,
                now_ns=now_ns,
            )
            return self._control_tx(conn, execution_id)

    def settle_recovery(
        self,
        execution_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphControlRecord:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            self._execution_tx(conn, execution_id)
            current = self._control_tx(conn, execution_id)
            if current.generation != expected_generation:
                raise ResearchGraphExecutionConflict(
                    "research graph control compare-and-swap conflict"
                )
            if current.phase is ResearchGraphControlPhase.PAUSED:
                return current
            if current.phase is not ResearchGraphControlPhase.RECOVERY_REQUIRED:
                raise ResearchGraphExecutionConflict(
                    "research graph recovery settlement requires recovery_required phase"
                )
            active = self._active_node_rows_tx(conn, execution_id)
            debt = self._reconciliation_node_ids_tx(conn, execution_id)
            if active or debt:
                raise ResearchGraphExecutionConflict(
                    "research graph recovery cannot settle before all active/uncertain "
                    f"nodes are resolved: active={tuple(str(row[0]) for row in active)} "
                    f"reconcile={debt}"
                )
            self._write_control_phase_tx(
                conn,
                execution_id,
                expected_generation=expected_generation,
                phase=ResearchGraphControlPhase.PAUSED,
                now_ns=now_ns,
            )
            return self._control_tx(conn, execution_id)

    def active_cut(
        self,
        logical_execution_id: str,
    ) -> ResearchGraphActiveCutRef | None:
        if type(logical_execution_id) is not str or not logical_execution_id.strip():
            raise ValueError("research graph logical_execution_id must be non-empty")
        with self._connection() as conn:
            return self._active_cut_tx(conn, logical_execution_id)

    def active_execution_snapshot(
        self,
        logical_execution_id: str,
    ) -> ResearchGraphActiveExecutionSnapshot | None:
        if type(logical_execution_id) is not str or not logical_execution_id.strip():
            raise ValueError("research graph logical_execution_id must be non-empty")
        with self._connection() as conn:
            active = self._active_cut_tx(conn, logical_execution_id)
            if active is None:
                return None
            execution = self._snapshot_tx(conn, active.cut_id)
            control = self._control_tx(conn, active.cut_id)
            return ResearchGraphActiveExecutionSnapshot(
                active,
                execution,
                control,
            )

    def move_active_cut(
        self,
        logical_execution_id: str,
        cut_id: str,
        *,
        expected_cut_id: str | None = None,
        source_fence: ResearchGraphCutSwitchFence | None = None,
    ) -> ResearchGraphActiveCutRef:
        if type(logical_execution_id) is not str or not logical_execution_id.strip():
            raise ValueError("research graph logical_execution_id must be non-empty")
        require_sha256(cut_id, "research graph cut_id")
        if expected_cut_id is not None:
            require_sha256(expected_cut_id, "research graph expected_cut_id")
        if source_fence is not None:
            if not isinstance(source_fence, ResearchGraphCutSwitchFence):
                raise TypeError("research graph source_fence must be typed")
            if expected_cut_id is None:
                raise ValueError(
                    "research graph guarded cut switch requires expected_cut_id"
                )
            if source_fence.source_execution_id != expected_cut_id:
                raise ValueError(
                    "research graph cut switch fence source identity drifted"
                )
        with self._transaction() as conn:
            execution = self._execution_tx(conn, cut_id)
            current_row = conn.execute(
                "SELECT logical_execution_id,cut_id,research_revision_digest,"
                "graph_digest,generation FROM research_graph_active_cuts "
                "WHERE logical_execution_id=?",
                (logical_execution_id,),
            ).fetchone()
            if current_row is not None:
                current = self._decode_active_cut(current_row)
                if current.cut_id == cut_id:
                    return current
                if expected_cut_id is None or current.cut_id != expected_cut_id:
                    raise ResearchGraphExecutionConflict(
                        "research graph active cut compare-and-swap conflict"
                    )
                if source_fence is None:
                    raise ResearchGraphExecutionConflict(
                        "research graph active cut replacement requires an exact "
                        "source execution fence"
                    )
                if source_fence is not None:
                    if current.generation != source_fence.active_cut_generation:
                        raise ResearchGraphExecutionConflict(
                            "research graph active cut generation fence conflict"
                        )
                    source_execution = self._execution_tx(
                        conn,
                        source_fence.source_execution_id,
                    )
                    if int(source_execution[4]) != source_fence.execution_generation:
                        raise ResearchGraphExecutionConflict(
                            "research graph source execution generation fence conflict"
                        )
                    if self._control_tx(
                        conn,
                        source_fence.source_execution_id,
                    ) != source_fence.graph_control:
                        raise ResearchGraphExecutionConflict(
                            "research graph source control fence conflict"
                        )
                    for expected_control in source_fence.node_controls:
                        current_control = self._node_control_tx(
                            conn,
                            source_fence.source_execution_id,
                            expected_control.node_id,
                        )
                        if current_control != expected_control:
                            raise ResearchGraphExecutionConflict(
                                "research graph source node control fence conflict: "
                                f"{expected_control.node_id}"
                            )
                generation = current.generation + 1
                updated = conn.execute(
                    "UPDATE research_graph_active_cuts SET cut_id=?,"
                    "research_revision_digest=?,graph_digest=?,generation=? "
                    "WHERE logical_execution_id=? AND cut_id=? AND generation=?",
                    (
                        cut_id,
                        str(execution[3]),
                        str(execution[2]),
                        generation,
                        logical_execution_id,
                        expected_cut_id,
                        current.generation,
                    ),
                )
                if updated.rowcount != 1:
                    raise ResearchGraphExecutionConflict(
                        "research graph active cut compare-and-swap conflict"
                    )
            else:
                if expected_cut_id is not None:
                    raise ResearchGraphExecutionConflict(
                        "research graph active cut does not exist for expected cut"
                    )
                generation = 1
                conn.execute(
                    "INSERT INTO research_graph_active_cuts("
                    "logical_execution_id,cut_id,research_revision_digest,"
                    "graph_digest,generation) VALUES(?,?,?,?,?)",
                    (
                        logical_execution_id,
                        cut_id,
                        str(execution[3]),
                        str(execution[2]),
                        generation,
                    ),
                )
            row = conn.execute(
                "SELECT logical_execution_id,cut_id,research_revision_digest,"
                "graph_digest,generation FROM research_graph_active_cuts "
                "WHERE logical_execution_id=?",
                (logical_execution_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("research graph active cut update disappeared")
            return self._decode_active_cut(row)

    def mark_ready(
        self,
        execution_id: str,
        node_id: str,
        *,
        now_ns: int,
    ) -> ResearchGraphNodeExecutionRecord:
        return self.mark_ready_many(
            execution_id,
            (node_id,),
            now_ns=now_ns,
        )[0]

    def mark_ready_many(
        self,
        execution_id: str,
        node_ids: tuple[str, ...],
        *,
        now_ns: int,
    ) -> tuple[ResearchGraphNodeExecutionRecord, ...]:
        now_ns = self._require_now(now_ns)
        if type(node_ids) is not tuple or not node_ids:
            raise TypeError(
                "research graph ready batch must be a non-empty node-id tuple"
            )
        if any(
            type(node_id) is not str or not node_id.strip()
            for node_id in node_ids
        ):
            raise ValueError(
                "research graph ready batch node ids must be non-empty text"
            )
        ordered = tuple(sorted(node_ids))
        if len(ordered) != len(set(ordered)):
            raise ValueError("research graph ready batch node ids must be unique")

        with self._transaction() as conn:
            self._execution_tx(conn, execution_id)
            current_by_node = {
                row.node_id: row
                for row in self._nodes_tx(conn, execution_id, ordered)
            }
            changed: list[str] = []
            for node_id in ordered:
                current = current_by_node[node_id]
                if current.state is ResearchGraphLiveNodeState.READY:
                    continue
                allowed = current.state is ResearchGraphLiveNodeState.PENDING
                if current.state is ResearchGraphLiveNodeState.RETRY_WAIT:
                    allowed = (
                        current.retry_not_before_ns is not None
                        and current.retry_not_before_ns <= now_ns
                    )
                if not allowed:
                    raise ResearchGraphExecutionConflict(
                        "cannot mark graph node ready from "
                        f"{current.state.value}: {node_id}"
                    )
                changed.append(node_id)

            if changed:
                conn.executemany(
                    "UPDATE research_graph_nodes "
                    "SET state=?,retry_not_before_ns=NULL "
                    "WHERE execution_id=? AND node_id=?",
                    (
                        (
                            ResearchGraphLiveNodeState.READY.value,
                            execution_id,
                            node_id,
                        )
                        for node_id in changed
                    ),
                )
            if changed:
                self._bump_generation(conn, execution_id)
            return self._nodes_tx(conn, execution_id, ordered)
    def claim(
        self,
        execution_id: str,
        node_id: str,
        *,
        owner_id: str,
        now_ns: int,
        lease_expires_at_ns: int,
    ) -> ResearchGraphNodeExecutionRecord:
        now_ns = self._require_now(now_ns)
        if type(owner_id) is not str or not owner_id.strip():
            raise ValueError("research graph owner_id must be non-empty")
        lease_expires_at_ns = self._require_timestamp_ns(
            lease_expires_at_ns,
            "research graph lease_expires_at_ns",
        )
        if lease_expires_at_ns <= now_ns:
            raise ValueError("research graph lease must expire after now")
        with self._transaction() as conn:
            current = self._node_tx(conn, execution_id, node_id)
            if current.state is not ResearchGraphLiveNodeState.READY:
                raise ResearchGraphExecutionConflict(
                    f"node is not claimable from {current.state.value}"
                )
            graph_control = self._control_tx(conn, execution_id)
            if graph_control.phase is not ResearchGraphControlPhase.ACTIVE:
                raise ResearchGraphExecutionConflict(
                    "research graph claim requires active graph control; "
                    f"actual={graph_control.phase.value}"
                )
            node_control = self._node_control_tx(conn, execution_id, node_id)
            if node_control.phase is not ResearchGraphNodeControlPhase.ACTIVE:
                raise ResearchGraphExecutionConflict(
                    "research graph claim requires active node control; "
                    f"{node_id}={node_control.phase.value}"
                )
            attempt_number = current.attempt_number + 1
            attempt_id = (
                f"{execution_id}:{node_id}:{attempt_number}:{uuid4().hex}"
            )
            conn.execute(
                "UPDATE research_graph_nodes SET "
                "state=?,attempt_number=?,attempt_id=?,lease_owner_id=?,"
                "lease_expires_at_ns=?,retry_not_before_ns=NULL,"
                "failure_type=NULL,failure_message=NULL,failure_provenance_json=NULL,blockers_json='[]' "
                "WHERE execution_id=? AND node_id=?",
                (
                    ResearchGraphLiveNodeState.CLAIMED.value,
                    attempt_number,
                    attempt_id,
                    owner_id,
                    lease_expires_at_ns,
                    execution_id,
                    node_id,
                ),
            )
            conn.execute(
                "INSERT INTO research_graph_attempts("
                "execution_id,node_id,attempt_number,attempt_id,owner_id,state,"
                "claimed_at_ns,lease_expires_at_ns"
                ") VALUES(?,?,?,?,?,?,?,?)",
                (
                    execution_id,
                    node_id,
                    attempt_number,
                    attempt_id,
                    owner_id,
                    ResearchGraphAttemptState.CLAIMED.value,
                    now_ns,
                    lease_expires_at_ns,
                ),
            )
            self._bump_generation(conn, execution_id)
            return self._node_tx(conn, execution_id, node_id)

    @staticmethod
    def _require_active(
        current: ResearchGraphNodeExecutionRecord,
        *,
        attempt_id: str,
        owner_id: str,
        expected_state: ResearchGraphLiveNodeState | None = None,
    ) -> None:
        if expected_state is not None and current.state is not expected_state:
            raise ResearchGraphExecutionConflict(
                f"node state is {current.state.value}, expected {expected_state.value}"
            )
        if current.state not in {
            ResearchGraphLiveNodeState.CLAIMED,
            ResearchGraphLiveNodeState.RUNNING,
        }:
            raise ResearchGraphExecutionConflict(
                f"node has no active lease in state {current.state.value}"
            )
        if current.attempt_id != attempt_id or current.lease_owner_id != owner_id:
            raise ResearchGraphExecutionConflict(
                "research graph attempt/lease ownership mismatch"
            )

    @staticmethod
    def _require_unexpired_lease(
        current: ResearchGraphNodeExecutionRecord,
        *,
        now_ns: int,
    ) -> None:
        if (
            current.lease_expires_at_ns is None
            or current.lease_expires_at_ns <= now_ns
        ):
            raise ResearchGraphExecutionConflict(
                "research graph lease expired; stale worker is fenced"
            )

    def mark_running(
        self,
        execution_id: str,
        node_id: str,
        *,
        attempt_id: str,
        owner_id: str,
        now_ns: int,
    ) -> ResearchGraphNodeExecutionRecord:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            current = self._node_tx(conn, execution_id, node_id)
            self._require_active(
                current,
                attempt_id=attempt_id,
                owner_id=owner_id,
                expected_state=ResearchGraphLiveNodeState.CLAIMED,
            )
            self._require_unexpired_lease(current, now_ns=now_ns)
            conn.execute(
                "UPDATE research_graph_nodes SET state=? "
                "WHERE execution_id=? AND node_id=?",
                (
                    ResearchGraphLiveNodeState.RUNNING.value,
                    execution_id,
                    node_id,
                ),
            )
            conn.execute(
                "UPDATE research_graph_attempts SET state=?,started_at_ns=? "
                "WHERE attempt_id=?",
                (
                    ResearchGraphAttemptState.RUNNING.value,
                    now_ns,
                    attempt_id,
                ),
            )
            self._bump_generation(conn, execution_id)
            return self._node_tx(conn, execution_id, node_id)

    def abandon_claim(
        self,
        execution_id: str,
        node_id: str,
        *,
        attempt_id: str,
        owner_id: str,
        now_ns: int,
    ) -> ResearchGraphNodeExecutionRecord:
        """Return one exact never-started claim to READY.

        This transition is safe after lease expiry because it can only remove
        the exact CLAIMED attempt owned by owner_id. A replacement claim or
        RUNNING generation fails the CAS instead of being retargeted.
        """

        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            current = self._node_tx(conn, execution_id, node_id)
            self._require_active(
                current,
                attempt_id=attempt_id,
                owner_id=owner_id,
                expected_state=ResearchGraphLiveNodeState.CLAIMED,
            )
            attempt_state = (
                ResearchGraphAttemptState.EXPIRED_BEFORE_START
                if current.lease_expires_at_ns is not None
                and current.lease_expires_at_ns <= now_ns
                else ResearchGraphAttemptState.ABANDONED_BEFORE_START
            )
            updated = conn.execute(
                "UPDATE research_graph_nodes SET state=?,attempt_id=NULL,"
                "lease_owner_id=NULL,lease_expires_at_ns=NULL "
                "WHERE execution_id=? AND node_id=? AND state=? "
                "AND attempt_id=? AND lease_owner_id=?",
                (
                    ResearchGraphLiveNodeState.READY.value,
                    execution_id,
                    node_id,
                    ResearchGraphLiveNodeState.CLAIMED.value,
                    attempt_id,
                    owner_id,
                ),
            )
            if updated.rowcount != 1:
                raise ResearchGraphExecutionConflict(
                    "research graph claimed-attempt recovery lost authority"
                )
            history = conn.execute(
                "UPDATE research_graph_attempts SET state=?,finished_at_ns=? "
                "WHERE attempt_id=? AND owner_id=? AND state=?",
                (
                    attempt_state.value,
                    now_ns,
                    attempt_id,
                    owner_id,
                    ResearchGraphAttemptState.CLAIMED.value,
                ),
            )
            if history.rowcount != 1:
                raise ResearchGraphExecutionConflict(
                    "research graph claim history recovery lost exact attempt"
                )
            self._bump_generation(conn, execution_id)
            return self._node_tx(conn, execution_id, node_id)

    def recover_expired_attempt(
        self,
        execution_id: str,
        node_id: str,
        *,
        attempt_id: str,
        owner_id: str,
        now_ns: int,
    ) -> ResearchGraphNodeExecutionRecord:
        """Recover one exact expired claim/run without touching peer nodes."""

        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            current = self._node_tx(conn, execution_id, node_id)
            if (
                current.state
                not in {
                    ResearchGraphLiveNodeState.CLAIMED,
                    ResearchGraphLiveNodeState.RUNNING,
                }
                or current.attempt_id != attempt_id
                or current.lease_owner_id != owner_id
            ):
                raise ResearchGraphExecutionConflict(
                    "research graph expired-attempt recovery lost exact authority"
                )
            if (
                current.lease_expires_at_ns is None
                or current.lease_expires_at_ns > now_ns
            ):
                raise ResearchGraphExecutionConflict(
                    "research graph attempt lease has not expired"
                )

            if current.state is ResearchGraphLiveNodeState.CLAIMED:
                node_state = ResearchGraphLiveNodeState.READY
                attempt_state = ResearchGraphAttemptState.EXPIRED_BEFORE_START
                conn.execute(
                    "UPDATE research_graph_nodes SET state=?,attempt_id=NULL,"
                    "lease_owner_id=NULL,lease_expires_at_ns=NULL "
                    "WHERE execution_id=? AND node_id=? AND state=? "
                    "AND attempt_id=? AND lease_owner_id=?",
                    (
                        node_state.value,
                        execution_id,
                        node_id,
                        ResearchGraphLiveNodeState.CLAIMED.value,
                        attempt_id,
                        owner_id,
                    ),
                )
                history = conn.execute(
                    "UPDATE research_graph_attempts SET state=?,finished_at_ns=? "
                    "WHERE attempt_id=? AND owner_id=? AND state=?",
                    (
                        attempt_state.value,
                        now_ns,
                        attempt_id,
                        owner_id,
                        ResearchGraphAttemptState.CLAIMED.value,
                    ),
                )
                if history.rowcount != 1:
                    raise ResearchGraphExecutionConflict(
                        "research graph expired claim history lost exact attempt"
                    )
            else:
                node_state = ResearchGraphLiveNodeState.RECONCILE_REQUIRED
                updated = conn.execute(
                    "UPDATE research_graph_nodes SET state=?,"
                    "lease_owner_id=NULL,lease_expires_at_ns=NULL "
                    "WHERE execution_id=? AND node_id=? AND state=? "
                    "AND attempt_id=? AND lease_owner_id=?",
                    (
                        node_state.value,
                        execution_id,
                        node_id,
                        ResearchGraphLiveNodeState.RUNNING.value,
                        attempt_id,
                        owner_id,
                    ),
                )
                if updated.rowcount != 1:
                    raise ResearchGraphExecutionConflict(
                        "research graph expired run recovery lost exact attempt"
                    )
                history = conn.execute(
                    "UPDATE research_graph_attempts SET state=? "
                    "WHERE attempt_id=? AND owner_id=? AND state=?",
                    (
                        ResearchGraphAttemptState.RECONCILE_REQUIRED.value,
                        attempt_id,
                        owner_id,
                        ResearchGraphAttemptState.RUNNING.value,
                    ),
                )
                if history.rowcount != 1:
                    raise ResearchGraphExecutionConflict(
                        "research graph expired run history lost exact attempt"
                    )
                node_control = self._node_control_tx(
                    conn, execution_id, node_id
                )
                if (
                    node_control.phase
                    is not ResearchGraphNodeControlPhase.RECOVERY_REQUIRED
                ):
                    self._write_node_control_phase_tx(
                        conn,
                        execution_id,
                        node_id,
                        expected_generation=node_control.generation,
                        phase=ResearchGraphNodeControlPhase.RECOVERY_REQUIRED,
                        now_ns=now_ns,
                    )

            self._bump_generation(conn, execution_id)
            return self._node_tx(conn, execution_id, node_id)

    def relinquish_running_attempt(
        self,
        execution_id: str,
        node_id: str,
        *,
        attempt_id: str,
        owner_id: str,
        now_ns: int,
    ) -> ResearchGraphNodeExecutionRecord:
        """Relinquish one exact RUNNING attempt after local worker convergence.

        Unlike expiry recovery, this transition does not wait for TTL because the
        owning scheduler has already joined its structured task groups. Scientific
        effect truth is intentionally not guessed: RUNNING always enters
        RECONCILE_REQUIRED and must be settled by the lower reconciliation authority.
        """

        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            current = self._node_tx(conn, execution_id, node_id)
            self._require_active(
                current,
                attempt_id=attempt_id,
                owner_id=owner_id,
                expected_state=ResearchGraphLiveNodeState.RUNNING,
            )
            updated = conn.execute(
                "UPDATE research_graph_nodes SET state=?,"
                "lease_owner_id=NULL,lease_expires_at_ns=NULL "
                "WHERE execution_id=? AND node_id=? AND state=? "
                "AND attempt_id=? AND lease_owner_id=?",
                (
                    ResearchGraphLiveNodeState.RECONCILE_REQUIRED.value,
                    execution_id,
                    node_id,
                    ResearchGraphLiveNodeState.RUNNING.value,
                    attempt_id,
                    owner_id,
                ),
            )
            if updated.rowcount != 1:
                raise ResearchGraphExecutionConflict(
                    "research graph running-attempt relinquish lost exact authority"
                )
            history = conn.execute(
                "UPDATE research_graph_attempts SET state=? "
                "WHERE attempt_id=? AND owner_id=? AND state=?",
                (
                    ResearchGraphAttemptState.RECONCILE_REQUIRED.value,
                    attempt_id,
                    owner_id,
                    ResearchGraphAttemptState.RUNNING.value,
                ),
            )
            if history.rowcount != 1:
                raise ResearchGraphExecutionConflict(
                    "research graph running-attempt relinquish lost exact history"
                )
            node_control = self._node_control_tx(conn, execution_id, node_id)
            if (
                node_control.phase
                is not ResearchGraphNodeControlPhase.RECOVERY_REQUIRED
            ):
                self._write_node_control_phase_tx(
                    conn,
                    execution_id,
                    node_id,
                    expected_generation=node_control.generation,
                    phase=ResearchGraphNodeControlPhase.RECOVERY_REQUIRED,
                    now_ns=now_ns,
                )
            self._bump_generation(conn, execution_id)
            return self._node_tx(conn, execution_id, node_id)

    def renew_leases(
        self,
        execution_id: str,
        renewals: tuple[ResearchGraphLeaseRenewal, ...],
        *,
        now_ns: int,
        wait_timeout_seconds: float | None = None,
    ) -> tuple[ResearchGraphNodeExecutionRecord, ...]:
        now_ns = self._require_now(now_ns)
        if type(renewals) is not tuple or not renewals or any(
            type(row) is not ResearchGraphLeaseRenewal for row in renewals
        ):
            raise TypeError(
                "research graph lease renewals must be a non-empty typed tuple"
            )
        ordered = tuple(sorted(renewals, key=lambda row: row.node_id))
        node_ids = tuple(row.node_id for row in ordered)
        attempt_ids = tuple(row.attempt_id for row in ordered)
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("research graph lease renewal node ids must be unique")
        if len(attempt_ids) != len(set(attempt_ids)):
            raise ValueError("research graph lease renewal attempt ids must be unique")
        normalized_expiries = {
            row.node_id: self._require_timestamp_ns(
                row.lease_expires_at_ns,
                "research graph renewed lease_expires_at_ns",
            )
            for row in ordered
        }
        if any(value <= now_ns for value in normalized_expiries.values()):
            raise ValueError("research graph renewed leases must expire after now")

        # Lease renewal is a liveness-critical authority transition. Once it is
        # waiting, ordinary graph writes must not barge ahead and consume the
        # remaining TTL. The current writer is allowed to finish atomically.
        with self._transaction(
            priority=True,
            timeout_seconds=wait_timeout_seconds,
        ) as conn:
            self._execution_tx(conn, execution_id)
            current_by_node = {
                row.node_id: row
                for row in self._nodes_tx(conn, execution_id, node_ids)
            }
            for renewal in ordered:
                current = current_by_node[renewal.node_id]
                self._require_active(
                    current,
                    attempt_id=renewal.attempt_id,
                    owner_id=renewal.owner_id,
                )
                self._require_unexpired_lease(current, now_ns=now_ns)
                expires_at_ns = normalized_expiries[renewal.node_id]
                if (
                    current.lease_expires_at_ns is None
                    or expires_at_ns <= current.lease_expires_at_ns
                ):
                    raise ValueError(
                        "research graph lease renewal must extend every lease"
                    )
                current_by_node[renewal.node_id] = current

            node_updates = tuple(
                (
                    normalized_expiries[renewal.node_id],
                    execution_id,
                    renewal.node_id,
                )
                for renewal in ordered
            )
            conn.executemany(
                "UPDATE research_graph_nodes SET lease_expires_at_ns=? "
                "WHERE execution_id=? AND node_id=?",
                node_updates,
            )
            attempt_updates = tuple(
                (
                    normalized_expiries[renewal.node_id],
                    execution_id,
                    renewal.node_id,
                    renewal.attempt_id,
                )
                for renewal in ordered
            )
            updated = conn.executemany(
                "UPDATE research_graph_attempts SET lease_expires_at_ns=? "
                "WHERE execution_id=? AND node_id=? AND attempt_id=?",
                attempt_updates,
            )
            if updated.rowcount != len(ordered):
                raise ResearchGraphExecutionConflict(
                    "research graph lease renewal lost exact attempt identity"
                )
            self._bump_generation(conn, execution_id)
            return self._nodes_tx(conn, execution_id, node_ids)

    def mark_succeeded(
        self,
        execution_id: str,
        node_id: str,
        *,
        attempt_id: str,
        owner_id: str,
        now_ns: int,
    ) -> ResearchGraphNodeExecutionRecord:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            current = self._node_tx(conn, execution_id, node_id)
            self._require_active(
                current,
                attempt_id=attempt_id,
                owner_id=owner_id,
                expected_state=ResearchGraphLiveNodeState.RUNNING,
            )
            self._require_unexpired_lease(current, now_ns=now_ns)
            conn.execute(
                "UPDATE research_graph_nodes SET state=?,attempt_id=NULL,"
                "lease_owner_id=NULL,lease_expires_at_ns=NULL "
                "WHERE execution_id=? AND node_id=?",
                (
                    ResearchGraphLiveNodeState.SUCCEEDED.value,
                    execution_id,
                    node_id,
                ),
            )
            conn.execute(
                "UPDATE research_graph_attempts SET state=?,finished_at_ns=? "
                "WHERE attempt_id=?",
                (
                    ResearchGraphAttemptState.SUCCEEDED.value,
                    now_ns,
                    attempt_id,
                ),
            )
            self._bump_generation(conn, execution_id)
            return self._node_tx(conn, execution_id, node_id)

    def mark_failed(
        self,
        execution_id: str,
        node_id: str,
        *,
        attempt_id: str,
        owner_id: str,
        now_ns: int,
        failure_type: str,
        failure_message: str,
        failure_provenance: ResearchGraphFailureProvenance,
    ) -> ResearchGraphNodeExecutionRecord:
        now_ns = self._require_now(now_ns)
        if type(failure_type) is not str or not failure_type.strip():
            raise ValueError("research graph failure_type must be non-empty")
        if type(failure_message) is not str or not failure_message.strip():
            raise ValueError("research graph failure_message must be non-empty")
        if not isinstance(failure_provenance, ResearchGraphFailureProvenance):
            raise TypeError("research graph failure_provenance must be typed")
        provenance_json = self._encode_failure_provenance(failure_provenance)
        with self._transaction() as conn:
            current = self._node_tx(conn, execution_id, node_id)
            self._require_active(
                current,
                attempt_id=attempt_id,
                owner_id=owner_id,
                expected_state=ResearchGraphLiveNodeState.RUNNING,
            )
            self._require_unexpired_lease(current, now_ns=now_ns)
            conn.execute(
                "UPDATE research_graph_nodes SET state=?,attempt_id=NULL,"
                "lease_owner_id=NULL,lease_expires_at_ns=NULL,"
                "failure_type=?,failure_message=?,failure_provenance_json=? "
                "WHERE execution_id=? AND node_id=?",
                (
                    ResearchGraphLiveNodeState.FAILED.value,
                    failure_type.strip(),
                    failure_message.strip(),
                    provenance_json,
                    execution_id,
                    node_id,
                ),
            )
            conn.execute(
                "UPDATE research_graph_attempts SET state=?,finished_at_ns=?,"
                "failure_type=?,failure_message=?,failure_provenance_json=? "
                "WHERE attempt_id=?",
                (
                    ResearchGraphAttemptState.FAILED.value,
                    now_ns,
                    failure_type.strip(),
                    failure_message.strip(),
                    provenance_json,
                    attempt_id,
                ),
            )
            self._bump_generation(conn, execution_id)
            return self._node_tx(conn, execution_id, node_id)

    def mark_blocked(
        self,
        execution_id: str,
        node_id: str,
        *,
        blocked_by_node_ids: tuple[str, ...],
    ) -> ResearchGraphNodeExecutionRecord:
        return self.mark_blocked_many(
            execution_id,
            ((node_id, blocked_by_node_ids),),
        )[0]

    def mark_blocked_many(
        self,
        execution_id: str,
        transitions: tuple[tuple[str, tuple[str, ...]], ...],
    ) -> tuple[ResearchGraphNodeExecutionRecord, ...]:
        if type(transitions) is not tuple or not transitions:
            raise TypeError(
                "research graph blocked batch must be a non-empty tuple"
            )
        normalized: list[tuple[str, tuple[str, ...]]] = []
        for row in transitions:
            if type(row) is not tuple or len(row) != 2:
                raise TypeError(
                    "research graph blocked batch rows must be "
                    "(node_id, blocker_ids) tuples"
                )
            node_id, blocked_by_node_ids = row
            if type(node_id) is not str or not node_id.strip():
                raise ValueError(
                    "research graph blocked batch node ids must be non-empty"
                )
            if (
                type(blocked_by_node_ids) is not tuple
                or not blocked_by_node_ids
            ):
                raise ValueError(
                    "blocked graph node requires blocker ids"
                )
            blockers = tuple(sorted(blocked_by_node_ids))
            if any(
                type(value) is not str or not value.strip()
                for value in blockers
            ):
                raise ValueError(
                    "research graph blocker ids must be non-empty"
                )
            if len(blockers) != len(set(blockers)):
                raise ValueError(
                    "research graph blocker ids must be unique"
                )
            normalized.append((node_id.strip(), blockers))

        ordered = tuple(sorted(normalized, key=lambda row: row[0]))
        node_ids = tuple(row[0] for row in ordered)
        if len(node_ids) != len(set(node_ids)):
            raise ValueError(
                "research graph blocked batch node ids must be unique"
            )

        with self._transaction() as conn:
            self._execution_tx(conn, execution_id)
            current_by_node = {
                row.node_id: row
                for row in self._nodes_tx(conn, execution_id, node_ids)
            }
            changed: list[tuple[str, tuple[str, ...]]] = []
            for node_id, blockers in ordered:
                current = current_by_node[node_id]
                if current.state is ResearchGraphLiveNodeState.BLOCKED:
                    if current.blocked_by_node_ids != blockers:
                        raise ResearchGraphExecutionConflict(
                            "blocked graph node already has different blockers: "
                            f"{node_id}"
                        )
                    continue
                if current.state not in {
                    ResearchGraphLiveNodeState.PENDING,
                    ResearchGraphLiveNodeState.READY,
                    ResearchGraphLiveNodeState.RETRY_WAIT,
                }:
                    raise ResearchGraphExecutionConflict(
                        "cannot block graph node from "
                        f"{current.state.value}: {node_id}"
                    )
                changed.append((node_id, blockers))

            if changed:
                conn.executemany(
                    "UPDATE research_graph_nodes "
                    "SET state=?,retry_not_before_ns=NULL,blockers_json=? "
                    "WHERE execution_id=? AND node_id=?",
                    (
                        (
                            ResearchGraphLiveNodeState.BLOCKED.value,
                            json.dumps(blockers, separators=(",", ":")),
                            execution_id,
                            node_id,
                        )
                        for node_id, blockers in changed
                    ),
                )
            if changed:
                self._bump_generation(conn, execution_id)
            return self._nodes_tx(conn, execution_id, node_ids)
    def _recover_active_rows_tx(
        self,
        conn: sqlite3.Connection,
        execution_id: str,
        rows: tuple[tuple[str, ResearchGraphLiveNodeState, str], ...],
        *,
        claimed_attempt_state: ResearchGraphAttemptState,
        now_ns: int,
    ) -> None:
        if not rows:
            return
        claimed = tuple(
            (node_id, attempt_id)
            for node_id, state, attempt_id in rows
            if state is ResearchGraphLiveNodeState.CLAIMED
        )
        running = tuple(
            (node_id, attempt_id)
            for node_id, state, attempt_id in rows
            if state is ResearchGraphLiveNodeState.RUNNING
        )
        if len(claimed) + len(running) != len(rows):
            raise RuntimeError("research graph recovery received non-active state")

        claimed_nodes = tuple(node_id for node_id, _attempt_id in claimed)
        claimed_attempts = tuple(attempt_id for _node_id, attempt_id in claimed)
        running_nodes = tuple(node_id for node_id, _attempt_id in running)
        running_attempts = tuple(attempt_id for _node_id, attempt_id in running)

        for offset in range(0, len(claimed_nodes), _SQLITE_IN_BATCH):
            batch = claimed_nodes[offset : offset + _SQLITE_IN_BATCH]
            placeholders = ",".join("?" for _ in batch)
            conn.execute(
                "UPDATE research_graph_nodes SET state=?,attempt_id=NULL,"
                "lease_owner_id=NULL,lease_expires_at_ns=NULL "
                "WHERE execution_id=? "
                f"AND node_id IN ({placeholders})",
                (
                    ResearchGraphLiveNodeState.READY.value,
                    execution_id,
                    *batch,
                ),
            )
        for offset in range(0, len(claimed_attempts), _SQLITE_IN_BATCH):
            batch = claimed_attempts[offset : offset + _SQLITE_IN_BATCH]
            placeholders = ",".join("?" for _ in batch)
            conn.execute(
                "UPDATE research_graph_attempts SET state=?,finished_at_ns=? "
                f"WHERE attempt_id IN ({placeholders})",
                (claimed_attempt_state.value, now_ns, *batch),
            )

        for offset in range(0, len(running_nodes), _SQLITE_IN_BATCH):
            batch = running_nodes[offset : offset + _SQLITE_IN_BATCH]
            placeholders = ",".join("?" for _ in batch)
            conn.execute(
                "UPDATE research_graph_nodes SET state=?,"
                "lease_owner_id=NULL,lease_expires_at_ns=NULL "
                "WHERE execution_id=? "
                f"AND node_id IN ({placeholders})",
                (
                    ResearchGraphLiveNodeState.RECONCILE_REQUIRED.value,
                    execution_id,
                    *batch,
                ),
            )
            conn.execute(
                "UPDATE research_graph_node_control "
                "SET phase=?,generation=generation+1,updated_at_ns=? "
                "WHERE execution_id=? "
                f"AND node_id IN ({placeholders}) AND phase<>?",
                (
                    ResearchGraphNodeControlPhase.RECOVERY_REQUIRED.value,
                    now_ns,
                    execution_id,
                    *batch,
                    ResearchGraphNodeControlPhase.RECOVERY_REQUIRED.value,
                ),
            )
        for offset in range(0, len(running_attempts), _SQLITE_IN_BATCH):
            batch = running_attempts[offset : offset + _SQLITE_IN_BATCH]
            placeholders = ",".join("?" for _ in batch)
            conn.execute(
                "UPDATE research_graph_attempts SET state=? "
                f"WHERE attempt_id IN ({placeholders})",
                (ResearchGraphAttemptState.RECONCILE_REQUIRED.value, *batch),
            )

        self._advance_generation(conn, execution_id, len(rows))

    def recover_abandoned_owner_generation(
        self,
        execution_id: str,
        *,
        current_owner_generation_id: str,
        now_ns: int,
    ) -> ResearchGraphExecutionSnapshot:
        """Fence a foreign owner only after its durable lease has expired.

        A different local owner-generation ID is not a proof of death:
        another RUN request may arrive while the original process is alive.
        Until an external owner-death witness exists, the durable lease expiry
        is the sole safe admission cut; unexpired or unknown leases must not
        be taken from the active execution.
        """

        now_ns = self._require_now(now_ns)
        if (
            type(current_owner_generation_id) is not str
            or not current_owner_generation_id.strip()
            or current_owner_generation_id != current_owner_generation_id.strip()
        ):
            raise ValueError(
                "research graph current_owner_generation_id must be canonical text"
            )
        current_prefix = (
            "research-graph-scheduler:"
            + current_owner_generation_id
            + ":"
        )
        with self._transaction() as conn:
            self._execution_tx(conn, execution_id)
            raw_rows = conn.execute(
                "SELECT node_id,state,attempt_id,lease_owner_id,lease_expires_at_ns "
                "FROM research_graph_nodes "
                "WHERE execution_id=? AND state IN (?,?) "
                "AND lease_expires_at_ns IS NOT NULL AND lease_expires_at_ns<=? "
                "ORDER BY node_id",
                (
                    execution_id,
                    ResearchGraphLiveNodeState.CLAIMED.value,
                    ResearchGraphLiveNodeState.RUNNING.value,
                    now_ns,
                ),
            ).fetchall()
            stale = tuple(
                (
                    str(row[0]),
                    ResearchGraphLiveNodeState(str(row[1])),
                    str(row[2]),
                )
                for row in raw_rows
                if not str(row[3]).startswith(current_prefix)
            )
            self._recover_active_rows_tx(
                conn,
                execution_id,
                stale,
                claimed_attempt_state=(
                    ResearchGraphAttemptState.ABANDONED_BEFORE_START
                ),
                now_ns=now_ns,
            )
            return self._snapshot_tx(conn, execution_id)

    def recover_expired(
        self,
        execution_id: str,
        *,
        now_ns: int,
    ) -> ResearchGraphExecutionSnapshot:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            self._execution_tx(conn, execution_id)
            raw_rows = conn.execute(
                "SELECT node_id,state,attempt_id FROM research_graph_nodes "
                "WHERE execution_id=? AND state IN (?,?) "
                "AND lease_expires_at_ns IS NOT NULL AND lease_expires_at_ns<=? "
                "ORDER BY node_id",
                (
                    execution_id,
                    ResearchGraphLiveNodeState.CLAIMED.value,
                    ResearchGraphLiveNodeState.RUNNING.value,
                    now_ns,
                ),
            ).fetchall()
            expired = tuple(
                (
                    str(row[0]),
                    ResearchGraphLiveNodeState(str(row[1])),
                    str(row[2]),
                )
                for row in raw_rows
            )
            self._recover_active_rows_tx(
                conn,
                execution_id,
                expired,
                claimed_attempt_state=(
                    ResearchGraphAttemptState.EXPIRED_BEFORE_START
                ),
                now_ns=now_ns,
            )
            return self._snapshot_tx(conn, execution_id)

    def retry_failed_subgraph(
        self,
        execution_id: str,
        failed_node_id: str,
        *,
        descendant_node_ids: tuple[str, ...],
        retry_not_before_ns: int,
    ) -> ResearchGraphExecutionSnapshot:
        if type(failed_node_id) is not str or not failed_node_id.strip():
            raise ValueError("research graph retry failed_node_id must be non-empty")
        if type(descendant_node_ids) is not tuple:
            raise TypeError("research graph retry descendants must be a tuple")
        descendants = tuple(sorted(descendant_node_ids))
        if (
            len(descendants) != len(set(descendants))
            or failed_node_id in descendants
            or any(type(node_id) is not str or not node_id.strip() for node_id in descendants)
        ):
            raise ValueError(
                "research graph retry descendants must be unique non-empty node ids "
                "excluding the failed root"
            )
        retry_not_before_ns = self._require_timestamp_ns(
            retry_not_before_ns,
            "research graph retry_not_before_ns",
        )
        with self._transaction() as conn:
            self._execution_tx(conn, execution_id)
            root = self._node_tx(conn, execution_id, failed_node_id)
            if root.state is not ResearchGraphLiveNodeState.FAILED:
                raise ResearchGraphExecutionConflict(
                    "research graph retry root must be definitively failed"
                )
            debt = self._reconciliation_node_ids_tx(conn, execution_id)
            if debt:
                raise ResearchGraphExecutionConflict(
                    "research graph retry is blocked by reconciliation debt: "
                    f"{debt}"
                )
            active = self._active_node_rows_tx(conn, execution_id)
            if active:
                raise ResearchGraphExecutionConflict(
                    "research graph retry requires a quiescent cut"
                )
            descendant_records = self._nodes_tx(
                conn,
                execution_id,
                descendants,
            )
            for record in descendant_records:
                if record.state not in {
                    ResearchGraphLiveNodeState.PENDING,
                    ResearchGraphLiveNodeState.READY,
                    ResearchGraphLiveNodeState.BLOCKED,
                }:
                    raise ResearchGraphExecutionConflict(
                        "research graph retry descendant has non-resettable state: "
                        f"{record.node_id}={record.state.value}"
                    )
            conn.execute(
                "UPDATE research_graph_nodes SET state=?,retry_not_before_ns=?,"
                "failure_type=NULL,failure_message=NULL,failure_provenance_json=NULL,blockers_json='[]' "
                "WHERE execution_id=? AND node_id=?",
                (
                    ResearchGraphLiveNodeState.RETRY_WAIT.value,
                    retry_not_before_ns,
                    execution_id,
                    failed_node_id,
                ),
            )
            for offset in range(0, len(descendants), _SQLITE_IN_BATCH):
                batch = descendants[offset : offset + _SQLITE_IN_BATCH]
                placeholders = ",".join("?" for _ in batch)
                updated = conn.execute(
                    "UPDATE research_graph_nodes SET state=?,retry_not_before_ns=NULL,"
                    "failure_type=NULL,failure_message=NULL,"
                    "failure_provenance_json=NULL,blockers_json='[]' "
                    "WHERE execution_id=? AND node_id IN ("
                    + placeholders
                    + ")",
                    (
                        ResearchGraphLiveNodeState.PENDING.value,
                        execution_id,
                        *batch,
                    ),
                )
                if updated.rowcount != len(batch):
                    raise ResearchGraphExecutionConflict(
                        "research graph retry descendant batch lost node identity"
                    )
            self._bump_generation(conn, execution_id)
            return self._snapshot_tx(conn, execution_id)

    def resolve_reconciliation(
        self,
        execution_id: str,
        node_id: str,
        *,
        disposition: ResearchGraphReconciliationDisposition,
        now_ns: int,
        retry_not_before_ns: int | None = None,
        failure_type: str | None = None,
        failure_message: str | None = None,
        failure_provenance: ResearchGraphFailureProvenance | None = None,
    ) -> ResearchGraphNodeExecutionRecord:
        now_ns = self._require_now(now_ns)
        if not isinstance(disposition, ResearchGraphReconciliationDisposition):
            raise TypeError("research graph reconciliation disposition must be typed")
        provenance_json = None
        if disposition is ResearchGraphReconciliationDisposition.FAILED:
            provenance_json = self._encode_failure_provenance(failure_provenance)
        elif failure_provenance is not None:
            raise ValueError("only failed reconciliation may carry failure provenance")
        with self._transaction() as conn:
            current = self._node_tx(conn, execution_id, node_id)
            if current.state is not ResearchGraphLiveNodeState.RECONCILE_REQUIRED:
                raise ResearchGraphExecutionConflict(
                    "graph node does not require reconciliation"
                )
            if current.attempt_id is None:
                raise RuntimeError("uncertain graph node lost attempt identity")
            attempt_id = current.attempt_id

            if disposition is ResearchGraphReconciliationDisposition.SUCCEEDED:
                node_state = ResearchGraphLiveNodeState.SUCCEEDED
                attempt_state = ResearchGraphAttemptState.RECONCILED_SUCCEEDED
                retry_value = None
                failure_type_value = None
                failure_message_value = None
            elif disposition is ResearchGraphReconciliationDisposition.RETRY:
                if retry_not_before_ns is None:
                    raise ValueError(
                        "reconciled retry requires retry_not_before_ns"
                    )
                retry_not_before_ns = self._require_timestamp_ns(
                    retry_not_before_ns,
                    "reconciled retry_not_before_ns",
                )
                node_state = ResearchGraphLiveNodeState.RETRY_WAIT
                attempt_state = ResearchGraphAttemptState.RECONCILED_RETRY
                retry_value = retry_not_before_ns
                failure_type_value = None
                failure_message_value = None
            else:
                if type(failure_type) is not str or not failure_type.strip():
                    raise ValueError(
                        "reconciled failure requires failure_type"
                    )
                if (
                    type(failure_message) is not str
                    or not failure_message.strip()
                ):
                    raise ValueError(
                        "reconciled failure requires failure_message"
                    )
                node_state = ResearchGraphLiveNodeState.FAILED
                attempt_state = ResearchGraphAttemptState.RECONCILED_FAILED
                retry_value = None
                failure_type_value = failure_type.strip()
                failure_message_value = failure_message.strip()

            conn.execute(
                "UPDATE research_graph_nodes SET state=?,attempt_id=NULL,"
                "lease_owner_id=NULL,lease_expires_at_ns=NULL,"
                "retry_not_before_ns=?,failure_type=?,failure_message=?,failure_provenance_json=? "
                "WHERE execution_id=? AND node_id=?",
                (
                    node_state.value,
                    retry_value,
                    failure_type_value,
                    failure_message_value,
                    provenance_json,
                    execution_id,
                    node_id,
                ),
            )
            conn.execute(
                "UPDATE research_graph_attempts SET state=?,finished_at_ns=?,"
                "failure_type=?,failure_message=?,failure_provenance_json=? WHERE attempt_id=?",
                (
                    attempt_state.value,
                    now_ns,
                    failure_type_value,
                    failure_message_value,
                    provenance_json,
                    attempt_id,
                ),
            )
            self._bump_generation(conn, execution_id)
            return self._node_tx(conn, execution_id, node_id)

    def mark_reused(
        self,
        execution_id: str,
        node_id: str,
        *,
        source_execution_id: str,
        source_node_id: str,
        semantic_digest: str,
        proof_digest: str,
        now_ns: int,
    ) -> ResearchGraphNodeExecutionRecord:
        now_ns = self._require_now(now_ns)
        require_sha256(semantic_digest, "research graph reuse semantic_digest")
        require_sha256(proof_digest, "research graph reuse proof_digest")
        if execution_id == source_execution_id:
            raise ValueError("research graph reuse must cross immutable execution cuts")
        with self._transaction() as conn:
            current = self._node_tx(conn, execution_id, node_id)
            source = self._node_tx(conn, source_execution_id, source_node_id)
            if current.state is ResearchGraphLiveNodeState.REUSED:
                existing = conn.execute(
                    "SELECT execution_id,node_id,source_execution_id,source_node_id,"
                    "semantic_digest,proof_digest,created_at_ns "
                    "FROM research_graph_reuse WHERE execution_id=? AND node_id=?",
                    (execution_id, node_id),
                ).fetchone()
                if existing is None:
                    raise RuntimeError("reused graph node lost its reuse proof")
                proof = self._decode_reuse(existing)
                if (
                    proof.source_execution_id != source_execution_id
                    or proof.source_node_id != source_node_id
                    or proof.semantic_digest != semantic_digest
                    or proof.proof_digest != proof_digest
                ):
                    raise ResearchGraphExecutionConflict(
                        "research graph node already reused from different proof"
                    )
                return current
            if current.state is not ResearchGraphLiveNodeState.PENDING:
                raise ResearchGraphExecutionConflict(
                    f"cannot reuse graph node from {current.state.value}"
                )
            if source.state not in {
                ResearchGraphLiveNodeState.SUCCEEDED,
                ResearchGraphLiveNodeState.REUSED,
            }:
                raise ResearchGraphExecutionConflict(
                    "research graph reuse source is not successfully completed"
                )
            if (
                current.semantic_digest != semantic_digest
                or source.semantic_digest != semantic_digest
            ):
                raise ResearchGraphExecutionConflict(
                    "research graph reuse semantic identity mismatch"
                )
            conn.execute(
                "INSERT INTO research_graph_reuse("
                "execution_id,node_id,source_execution_id,source_node_id,"
                "semantic_digest,proof_digest,created_at_ns) VALUES(?,?,?,?,?,?,?)",
                (
                    execution_id,
                    node_id,
                    source_execution_id,
                    source_node_id,
                    semantic_digest,
                    proof_digest,
                    now_ns,
                ),
            )
            conn.execute(
                "UPDATE research_graph_nodes SET state=? "
                "WHERE execution_id=? AND node_id=?",
                (
                    ResearchGraphLiveNodeState.REUSED.value,
                    execution_id,
                    node_id,
                ),
            )
            self._bump_generation(conn, execution_id)
            return self._node_tx(conn, execution_id, node_id)

    def reuse_record(
        self,
        execution_id: str,
        node_id: str,
    ) -> ResearchGraphReuseRecord | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT execution_id,node_id,source_execution_id,source_node_id,"
                "semantic_digest,proof_digest,created_at_ns "
                "FROM research_graph_reuse WHERE execution_id=? AND node_id=?",
                (execution_id, node_id),
            ).fetchone()
        return None if row is None else self._decode_reuse(row)

    def attempt_state(
        self,
        execution_id: str,
        node_id: str,
        attempt_number: int,
    ) -> ResearchGraphAttemptRecord:
        if type(attempt_number) is not int or attempt_number < 1:
            raise ValueError("research graph attempt_number must be positive")
        with self._connection() as conn:
            self._node_tx(conn, execution_id, node_id)
            row = conn.execute(
                "SELECT execution_id,node_id,attempt_number,attempt_id,owner_id,"
                "state,claimed_at_ns,lease_expires_at_ns,started_at_ns,"
                "finished_at_ns,failure_type,failure_message,failure_provenance_json "
                "FROM research_graph_attempts "
                "WHERE execution_id=? AND node_id=? AND attempt_number=?",
                (execution_id, node_id, attempt_number),
            ).fetchone()
        if row is None:
            raise ResearchGraphExecutionNotFound(
                f"research graph attempt not found: "
                f"{execution_id}:{node_id}:{attempt_number}"
            )
        return self._decode_attempt(row)

    def attempts(
        self,
        execution_id: str,
        node_id: str,
    ) -> tuple[ResearchGraphAttemptRecord, ...]:
        with self._connection() as conn:
            self._node_tx(conn, execution_id, node_id)
            rows = conn.execute(
                "SELECT execution_id,node_id,attempt_number,attempt_id,owner_id,"
                "state,claimed_at_ns,lease_expires_at_ns,started_at_ns,"
                "finished_at_ns,failure_type,failure_message,failure_provenance_json "
                "FROM research_graph_attempts "
                "WHERE execution_id=? AND node_id=? ORDER BY attempt_number",
                (execution_id, node_id),
            ).fetchall()
        return tuple(self._decode_attempt(row) for row in rows)


__all__ = ["SQLiteResearchGraphExecutionStore"]
