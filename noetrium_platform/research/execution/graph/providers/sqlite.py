from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from noetrium_platform.foundation.kernel.kernel import require_sha256
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphActiveCutRef,
    ResearchGraphAttemptRecord,
    ResearchGraphAttemptState,
    ResearchGraphControlPhase,
    ResearchGraphControlRecord,
    ResearchGraphExecutionConflict,
    ResearchGraphExecutionNotFound,
    ResearchGraphExecutionSnapshot,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeControlPhase,
    ResearchGraphNodeControlRecord,
    ResearchGraphNodeExecutionRecord,
    ResearchGraphPlan,
    ResearchGraphReconciliationDisposition,
    ResearchGraphReuseRecord,
)


class SQLiteResearchGraphExecutionStore:
    """Crash-durable graph orchestration state with attempt and lease history.

    This store owns only graph scheduling progress. Scientific execution state,
    effects, evidence and provider state stay in their lower canonical authorities.
    """

    SCHEMA_VERSION = 3

    def __init__(self, path: str | Path, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("research graph SQLite timeout must be positive")
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = float(timeout_seconds)
        with self._connection() as conn:
            self._ensure_schema(conn)

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(
            self.path,
            timeout=self.timeout_seconds,
            isolation_level=None,
        )
        try:
            conn.execute(
                f"PRAGMA busy_timeout={max(1, int(self.timeout_seconds * 1000))}"
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                if conn.in_transaction:
                    conn.rollback()
                raise

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
            "INSERT OR IGNORE INTO research_graph_meta(key,value) "
            "VALUES('schema_version',?)",
            (str(self.SCHEMA_VERSION),),
        )
        row = conn.execute(
            "SELECT value FROM research_graph_meta WHERE key='schema_version'"
        ).fetchone()
        if row is None or int(row[0]) != self.SCHEMA_VERSION:
            raise RuntimeError("unsupported SQLiteResearchGraphExecutionStore schema")

    @staticmethod
    def _decode_blockers(raw: object) -> tuple[str, ...]:
        values = json.loads(str(raw))
        if not isinstance(values, list) or any(type(value) is not str for value in values):
            raise RuntimeError("research graph blockers are corrupt")
        return tuple(values)

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
            blocked_by_node_ids=cls._decode_blockers(row[11]),
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
            "failure_type,failure_message,blockers_json "
            "FROM research_graph_nodes WHERE execution_id=? AND node_id=?",
            (execution_id, node_id),
        ).fetchone()
        if row is None:
            raise ResearchGraphExecutionNotFound(f"{execution_id}:{node_id}")
        return self._decode_node(row)

    def _snapshot_tx(
        self,
        conn: sqlite3.Connection,
        execution_id: str,
    ) -> ResearchGraphExecutionSnapshot:
        execution = self._execution_tx(conn, execution_id)
        rows = conn.execute(
            "SELECT execution_id,node_id,semantic_digest,state,attempt_number,"
            "attempt_id,lease_owner_id,lease_expires_at_ns,retry_not_before_ns,"
            "failure_type,failure_message,blockers_json "
            "FROM research_graph_nodes WHERE execution_id=? ORDER BY node_id",
            (execution_id,),
        ).fetchall()
        if not rows:
            raise RuntimeError("research graph execution has no node state")
        return ResearchGraphExecutionSnapshot(
            execution_id=str(execution[0]),
            graph_id=str(execution[1]),
            graph_digest=str(execution[2]),
            research_revision_digest=str(execution[3]),
            generation=int(execution[4]),
            nodes=tuple(self._decode_node(row) for row in rows),
        )

    @staticmethod
    def _bump_generation(conn: sqlite3.Connection, execution_id: str) -> None:
        updated = conn.execute(
            "UPDATE research_graph_executions SET generation=generation+1 "
            "WHERE execution_id=?",
            (execution_id,),
        )
        if updated.rowcount != 1:
            raise ResearchGraphExecutionNotFound(execution_id)

    @staticmethod
    def _require_now(now_ns: int) -> int:
        if type(now_ns) is not int or now_ns < 0:
            raise ValueError("research graph now_ns must be non-negative")
        return now_ns

    def ensure_execution(
        self,
        execution_id: str,
        plan: ResearchGraphPlan,
    ) -> ResearchGraphExecutionSnapshot:
        if type(execution_id) is not str or not execution_id.strip():
            raise ValueError("research graph execution_id must be non-empty")
        if type(plan) is not ResearchGraphPlan:
            raise TypeError("research graph durable execution requires ResearchGraphPlan")
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT graph_id,graph_digest,research_revision_digest "
                "FROM research_graph_executions WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO research_graph_executions("
                    "execution_id,graph_id,graph_digest,research_revision_digest,generation"
                    ") VALUES(?,?,?,?,1)",
                    (
                        execution_id,
                        plan.graph_id,
                        plan.graph_digest,
                        plan.research_revision_digest,
                    ),
                )
                conn.execute(
                    "INSERT INTO research_graph_control("
                    "execution_id,phase,generation,updated_at_ns"
                    ") VALUES(?,?,1,0)",
                    (
                        execution_id,
                        ResearchGraphControlPhase.ACTIVE.value,
                    ),
                )
                conn.executemany(
                    "INSERT INTO research_graph_node_control("
                    "execution_id,node_id,phase,generation,updated_at_ns"
                    ") VALUES(?,?,?,1,0)",
                    (
                        (
                            execution_id,
                            node.node_id,
                            ResearchGraphNodeControlPhase.ACTIVE.value,
                        )
                        for node in plan.nodes
                    ),
                )
                conn.executemany(
                    "INSERT INTO research_graph_nodes("
                    "execution_id,node_id,semantic_digest,state,attempt_number,"
                    "blockers_json) VALUES(?,?,?,?,0,'[]')",
                    (
                        (
                            execution_id,
                            node.node_id,
                            node.semantic_digest,
                            ResearchGraphLiveNodeState.PENDING.value,
                        )
                        for node in plan.nodes
                    ),
                )
            else:
                actual = (str(row[0]), str(row[1]), str(row[2]))
                expected = (
                    plan.graph_id,
                    plan.graph_digest,
                    plan.research_revision_digest,
                )
                if actual != expected:
                    raise ResearchGraphExecutionConflict(
                        "execution id is already bound to a different immutable ResearchGraph"
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
                node_controls = conn.execute(
                    "SELECT node_id FROM research_graph_node_control "
                    "WHERE execution_id=? ORDER BY node_id",
                    (execution_id,),
                ).fetchall()
                expected_control_ids = tuple(node.node_id for node in plan.nodes)
                actual_control_ids = tuple(str(row[0]) for row in node_controls)
                if actual_control_ids != expected_control_ids:
                    raise ResearchGraphExecutionConflict(
                        "durable graph node control identity differs from immutable plan"
                    )
                existing = conn.execute(
                    "SELECT node_id,semantic_digest FROM research_graph_nodes "
                    "WHERE execution_id=? ORDER BY node_id",
                    (execution_id,),
                ).fetchall()
                expected_nodes = tuple(
                    (node.node_id, node.semantic_digest) for node in plan.nodes
                )
                actual_nodes = tuple((str(row[0]), str(row[1])) for row in existing)
                if actual_nodes != expected_nodes:
                    raise ResearchGraphExecutionConflict(
                        "durable graph node identity differs from immutable plan"
                    )
            return self._snapshot_tx(conn, execution_id)

    def snapshot(self, execution_id: str) -> ResearchGraphExecutionSnapshot:
        with self._connection() as conn:
            return self._snapshot_tx(conn, execution_id)

    def control_state(
        self,
        execution_id: str,
    ) -> ResearchGraphControlRecord:
        with self._connection() as conn:
            self._execution_tx(conn, execution_id)
            return self._control_tx(conn, execution_id)

    def node_control_state(
        self,
        execution_id: str,
        node_id: str,
    ) -> ResearchGraphNodeControlRecord:
        with self._connection() as conn:
            self._execution_tx(conn, execution_id)
            self._node_tx(conn, execution_id, node_id)
            return self._node_control_tx(conn, execution_id, node_id)

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
                    "failure_type=NULL,failure_message=NULL,blockers_json='[]' "
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
            row = conn.execute(
                "SELECT logical_execution_id,cut_id,research_revision_digest,"
                "graph_digest,generation FROM research_graph_active_cuts "
                "WHERE logical_execution_id=?",
                (logical_execution_id,),
            ).fetchone()
        return None if row is None else self._decode_active_cut(row)

    def move_active_cut(
        self,
        logical_execution_id: str,
        cut_id: str,
        *,
        expected_cut_id: str | None = None,
    ) -> ResearchGraphActiveCutRef:
        if type(logical_execution_id) is not str or not logical_execution_id.strip():
            raise ValueError("research graph logical_execution_id must be non-empty")
        require_sha256(cut_id, "research graph cut_id")
        if expected_cut_id is not None:
            require_sha256(expected_cut_id, "research graph expected_cut_id")
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
                generation = current.generation + 1
                conn.execute(
                    "UPDATE research_graph_active_cuts SET cut_id=?,"
                    "research_revision_digest=?,graph_digest=?,generation=? "
                    "WHERE logical_execution_id=? AND cut_id=?",
                    (
                        cut_id,
                        str(execution[3]),
                        str(execution[2]),
                        generation,
                        logical_execution_id,
                        expected_cut_id,
                    ),
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
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            current = self._node_tx(conn, execution_id, node_id)
            if current.state is ResearchGraphLiveNodeState.READY:
                return current
            allowed = current.state is ResearchGraphLiveNodeState.PENDING
            if current.state is ResearchGraphLiveNodeState.RETRY_WAIT:
                allowed = (
                    current.retry_not_before_ns is not None
                    and current.retry_not_before_ns <= now_ns
                )
            if not allowed:
                raise ResearchGraphExecutionConflict(
                    f"cannot mark node ready from state {current.state.value}"
                )
            conn.execute(
                "UPDATE research_graph_nodes SET state=?,retry_not_before_ns=NULL "
                "WHERE execution_id=? AND node_id=?",
                (
                    ResearchGraphLiveNodeState.READY.value,
                    execution_id,
                    node_id,
                ),
            )
            self._bump_generation(conn, execution_id)
            return self._node_tx(conn, execution_id, node_id)

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
        if (
            type(lease_expires_at_ns) is not int
            or lease_expires_at_ns <= now_ns
        ):
            raise ValueError("research graph lease must expire after now")
        with self._transaction() as conn:
            current = self._node_tx(conn, execution_id, node_id)
            if current.state is not ResearchGraphLiveNodeState.READY:
                raise ResearchGraphExecutionConflict(
                    f"node is not claimable from {current.state.value}"
                )
            attempt_number = current.attempt_number + 1
            attempt_id = (
                f"{execution_id}:{node_id}:{attempt_number}:{uuid4().hex}"
            )
            conn.execute(
                "UPDATE research_graph_nodes SET "
                "state=?,attempt_number=?,attempt_id=?,lease_owner_id=?,"
                "lease_expires_at_ns=?,retry_not_before_ns=NULL,"
                "failure_type=NULL,failure_message=NULL,blockers_json='[]' "
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

    def renew_lease(
        self,
        execution_id: str,
        node_id: str,
        *,
        attempt_id: str,
        owner_id: str,
        now_ns: int,
        lease_expires_at_ns: int,
    ) -> ResearchGraphNodeExecutionRecord:
        now_ns = self._require_now(now_ns)
        if (
            type(lease_expires_at_ns) is not int
            or lease_expires_at_ns <= now_ns
        ):
            raise ValueError("research graph renewed lease must expire after now")
        with self._transaction() as conn:
            current = self._node_tx(conn, execution_id, node_id)
            self._require_active(
                current,
                attempt_id=attempt_id,
                owner_id=owner_id,
            )
            self._require_unexpired_lease(current, now_ns=now_ns)
            if lease_expires_at_ns <= current.lease_expires_at_ns:
                raise ValueError("research graph lease renewal must extend the lease")
            conn.execute(
                "UPDATE research_graph_nodes SET lease_expires_at_ns=? "
                "WHERE execution_id=? AND node_id=?",
                (lease_expires_at_ns, execution_id, node_id),
            )
            conn.execute(
                "UPDATE research_graph_attempts SET lease_expires_at_ns=? "
                "WHERE attempt_id=?",
                (lease_expires_at_ns, attempt_id),
            )
            self._bump_generation(conn, execution_id)
            return self._node_tx(conn, execution_id, node_id)

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
    ) -> ResearchGraphNodeExecutionRecord:
        now_ns = self._require_now(now_ns)
        if type(failure_type) is not str or not failure_type.strip():
            raise ValueError("research graph failure_type must be non-empty")
        if type(failure_message) is not str or not failure_message.strip():
            raise ValueError("research graph failure_message must be non-empty")
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
                "failure_type=?,failure_message=? "
                "WHERE execution_id=? AND node_id=?",
                (
                    ResearchGraphLiveNodeState.FAILED.value,
                    failure_type.strip(),
                    failure_message.strip(),
                    execution_id,
                    node_id,
                ),
            )
            conn.execute(
                "UPDATE research_graph_attempts SET state=?,finished_at_ns=?,"
                "failure_type=?,failure_message=? WHERE attempt_id=?",
                (
                    ResearchGraphAttemptState.FAILED.value,
                    now_ns,
                    failure_type.strip(),
                    failure_message.strip(),
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
        if type(blocked_by_node_ids) is not tuple or not blocked_by_node_ids:
            raise ValueError("blocked graph node requires blocker ids")
        blockers = tuple(sorted(blocked_by_node_ids))
        if any(type(value) is not str or not value.strip() for value in blockers):
            raise ValueError("research graph blocker ids must be non-empty")
        if len(blockers) != len(set(blockers)):
            raise ValueError("research graph blocker ids must be unique")
        with self._transaction() as conn:
            current = self._node_tx(conn, execution_id, node_id)
            if current.state is ResearchGraphLiveNodeState.BLOCKED:
                if current.blocked_by_node_ids != blockers:
                    raise ResearchGraphExecutionConflict(
                        "blocked graph node already has different blockers"
                    )
                return current
            if current.state not in {
                ResearchGraphLiveNodeState.PENDING,
                ResearchGraphLiveNodeState.READY,
                ResearchGraphLiveNodeState.RETRY_WAIT,
            }:
                raise ResearchGraphExecutionConflict(
                    f"cannot block graph node from {current.state.value}"
                )
            conn.execute(
                "UPDATE research_graph_nodes SET state=?,retry_not_before_ns=NULL,"
                "blockers_json=? WHERE execution_id=? AND node_id=?",
                (
                    ResearchGraphLiveNodeState.BLOCKED.value,
                    json.dumps(blockers, separators=(",", ":")),
                    execution_id,
                    node_id,
                ),
            )
            self._bump_generation(conn, execution_id)
            return self._node_tx(conn, execution_id, node_id)

    def recover_expired(
        self,
        execution_id: str,
        *,
        now_ns: int,
    ) -> ResearchGraphExecutionSnapshot:
        now_ns = self._require_now(now_ns)
        with self._transaction() as conn:
            self._execution_tx(conn, execution_id)
            rows = conn.execute(
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
            for row in rows:
                node_id = str(row[0])
                state = ResearchGraphLiveNodeState(str(row[1]))
                attempt_id = str(row[2])
                if state is ResearchGraphLiveNodeState.CLAIMED:
                    conn.execute(
                        "UPDATE research_graph_nodes SET state=?,attempt_id=NULL,"
                        "lease_owner_id=NULL,lease_expires_at_ns=NULL "
                        "WHERE execution_id=? AND node_id=?",
                        (
                            ResearchGraphLiveNodeState.READY.value,
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
                    conn.execute(
                        "UPDATE research_graph_nodes SET state=?,"
                        "lease_owner_id=NULL,lease_expires_at_ns=NULL "
                        "WHERE execution_id=? AND node_id=?",
                        (
                            ResearchGraphLiveNodeState.RECONCILE_REQUIRED.value,
                            execution_id,
                            node_id,
                        ),
                    )
                    conn.execute(
                        "UPDATE research_graph_attempts SET state=? "
                        "WHERE attempt_id=?",
                        (
                            ResearchGraphAttemptState.RECONCILE_REQUIRED.value,
                            attempt_id,
                        ),
                    )
                    node_control = self._node_control_tx(
                        conn,
                        execution_id,
                        node_id,
                    )
                    if node_control.phase is not (
                        ResearchGraphNodeControlPhase.RECOVERY_REQUIRED
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
        if type(retry_not_before_ns) is not int or retry_not_before_ns < 0:
            raise ValueError("research graph retry_not_before_ns must be non-negative")
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
            for node_id in descendants:
                record = self._node_tx(conn, execution_id, node_id)
                if record.state not in {
                    ResearchGraphLiveNodeState.PENDING,
                    ResearchGraphLiveNodeState.READY,
                    ResearchGraphLiveNodeState.BLOCKED,
                }:
                    raise ResearchGraphExecutionConflict(
                        "research graph retry descendant has non-resettable state: "
                        f"{node_id}={record.state.value}"
                    )
            conn.execute(
                "UPDATE research_graph_nodes SET state=?,retry_not_before_ns=?,"
                "failure_type=NULL,failure_message=NULL,blockers_json='[]' "
                "WHERE execution_id=? AND node_id=?",
                (
                    ResearchGraphLiveNodeState.RETRY_WAIT.value,
                    retry_not_before_ns,
                    execution_id,
                    failed_node_id,
                ),
            )
            for node_id in descendants:
                conn.execute(
                    "UPDATE research_graph_nodes SET state=?,retry_not_before_ns=NULL,"
                    "failure_type=NULL,failure_message=NULL,blockers_json='[]' "
                    "WHERE execution_id=? AND node_id=?",
                    (
                        ResearchGraphLiveNodeState.PENDING.value,
                        execution_id,
                        node_id,
                    ),
                )
            self._bump_generation(conn, execution_id)
            return self._snapshot_tx(conn, execution_id)

    def schedule_retry(
        self,
        execution_id: str,
        node_id: str,
        *,
        retry_not_before_ns: int,
    ) -> ResearchGraphNodeExecutionRecord:
        if type(retry_not_before_ns) is not int or retry_not_before_ns < 0:
            raise ValueError("research graph retry_not_before_ns must be non-negative")
        with self._transaction() as conn:
            current = self._node_tx(conn, execution_id, node_id)
            if current.state is not ResearchGraphLiveNodeState.FAILED:
                raise ResearchGraphExecutionConflict(
                    "only definitively failed graph nodes can be scheduled for retry"
                )
            conn.execute(
                "UPDATE research_graph_nodes SET state=?,retry_not_before_ns=?,"
                "failure_type=NULL,failure_message=NULL "
                "WHERE execution_id=? AND node_id=?",
                (
                    ResearchGraphLiveNodeState.RETRY_WAIT.value,
                    retry_not_before_ns,
                    execution_id,
                    node_id,
                ),
            )
            self._bump_generation(conn, execution_id)
            return self._node_tx(conn, execution_id, node_id)

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
    ) -> ResearchGraphNodeExecutionRecord:
        now_ns = self._require_now(now_ns)
        if not isinstance(disposition, ResearchGraphReconciliationDisposition):
            raise TypeError("research graph reconciliation disposition must be typed")
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
                if (
                    type(retry_not_before_ns) is not int
                    or retry_not_before_ns < 0
                ):
                    raise ValueError(
                        "reconciled retry requires retry_not_before_ns"
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
                "retry_not_before_ns=?,failure_type=?,failure_message=? "
                "WHERE execution_id=? AND node_id=?",
                (
                    node_state.value,
                    retry_value,
                    failure_type_value,
                    failure_message_value,
                    execution_id,
                    node_id,
                ),
            )
            conn.execute(
                "UPDATE research_graph_attempts SET state=?,finished_at_ns=?,"
                "failure_type=?,failure_message=? WHERE attempt_id=?",
                (
                    attempt_state.value,
                    now_ns,
                    failure_type_value,
                    failure_message_value,
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
                "finished_at_ns,failure_type,failure_message "
                "FROM research_graph_attempts "
                "WHERE execution_id=? AND node_id=? ORDER BY attempt_number",
                (execution_id, node_id),
            ).fetchall()
        return tuple(self._decode_attempt(row) for row in rows)


__all__ = ["SQLiteResearchGraphExecutionStore"]
