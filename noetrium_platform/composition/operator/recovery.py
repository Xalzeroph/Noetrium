"""Operator recovery orchestration; native graph/Machine stores retain authority."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import time
from uuid import uuid4

from noetrium_platform.foundation.kernel.kernel.durability import (
    atomic_replace_bytes,
    durable_sqlite_reader,
    durable_sqlite_connection,
    sqlite_read_snapshot,
)
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphLiveNodeState as State,
    ResearchGraphNodeControlPhase as NodePhase,
    ResearchGraphControlPhase as Phase,
    ResearchGraphReconciliationDisposition as Disposition,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)
from .cli_context import owner_alive, owner_identity, recovery_runtime_binding


def recovery_plan(row):
    """One coherent read-only observation per graph; creates no execution runtime."""
    graphs = []
    now = time.time_ns()
    paths = sorted(
        Path(row["data_root"]).glob("projects/root-sets/*/research/graph.v5.sqlite3")
    )
    for path in paths:
        if path.is_symlink():
            raise ValueError("recovery graph must not be a symlink")
        with durable_sqlite_reader(path, timeout_seconds=1) as conn:
            with sqlite_read_snapshot(conn):
                cuts = list(
                    conn.execute(
                        "SELECT a.logical_execution_id,a.cut_id,c.phase "
                        "FROM research_graph_active_cuts a JOIN research_graph_control c ON c.execution_id=a.cut_id"
                    )
                )
                for logical, cut, phase in cuts:
                    nodes = [
                        {
                            "node": node,
                            "state": state,
                            "attempt_number": number,
                            "attempt_id": attempt,
                            "lease_expires_at_ns": expires,
                            "blockers": json.loads(blockers),
                        }
                        for node, state, number, attempt, expires, blockers in conn.execute(
                            "SELECT node_id,state,attempt_number,attempt_id,lease_expires_at_ns,blockers_json "
                            "FROM research_graph_nodes WHERE execution_id=? ORDER BY node_id",
                            (cut,),
                        )
                    ]
                    graphs.append(
                        {
                            "path": str(path),
                            "logical_execution_id": logical,
                            "cut_id": cut,
                            "control_phase": phase,
                            "nodes": nodes,
                        }
                    )
    return {
        "run": row["name"],
        "observed_at_ns": now,
        "owner_alive": owner_alive(row),
        "runtime": recovery_runtime_binding(row),
        "graphs": graphs,
    }


@dataclass
class RecoverySession:
    path: Path
    document: dict

    def mark(self, phase, **fields):
        self.document.update(phase=phase, updated_at_ns=time.time_ns(), **fields)
        atomic_replace_bytes(
            self.path,
            (json.dumps(self.document, indent=2, ensure_ascii=False) + "\n").encode(),
        )


def _blocked_descendants(snapshot, root):
    selected = {root}
    changed = True
    while changed:
        changed = False
        for node in snapshot.nodes:
            if (
                node.state is State.BLOCKED
                and node.node_id not in selected
                and any(blocker in selected for blocker in node.blocked_by_node_ids)
            ):
                selected.add(node.node_id)
                changed = True
    return tuple(sorted(selected - {root}))


def prepare_recovery(row, *, retry_failed=False, retry_uncertain=False, reason=None):
    """Called under the run's execution lock, before claiming its new driver.

    Every mutation goes through the native graph store. Preparation is
    restartable: a second invocation observes committed intermediate state,
    finishes pending control settlement, and never recreates a finished attempt.
    """
    plan = recovery_plan(row)
    if plan["owner_alive"]:
        raise ValueError("run already has a live owner")
    if not plan["graphs"]:
        raise ValueError(
            "run has no durable graph; use research runs start for a prepared version"
        )
    if retry_uncertain and (not isinstance(reason, str) or not reason.strip()):
        raise ValueError(
            "--retry-uncertain requires --reason; external effects may execute again"
        )
    now = time.time_ns()
    for graph in plan["graphs"]:
        if graph["control_phase"] == "cancelled":
            raise ValueError(
                "cancelled executions cannot be recovered; create a fresh run"
            )
        for node in graph["nodes"]:
            state = node["state"]
            if state in ("running", "claimed"):
                expires = node["lease_expires_at_ns"]
                if expires is None or expires > now:
                    raise ValueError(
                        "active lease still protects a worker; wait for expiry before recovery"
                    )
            if state == "failed" and not retry_failed:
                raise ValueError("failed nodes require --retry-failed")
            if state in ("reconcile_required", "running") and not retry_uncertain:
                raise ValueError(
                    "uncertain work requires research reconcile, or explicit --retry-uncertain --reason"
                )
    folder = Path(row["data_root"]) / "recoveries" / uuid4().hex
    folder.mkdir(parents=True, mode=0o700)
    session = RecoverySession(
        folder / "session.json",
        {
            "schema": "noetrium.cli.recovery.v1",
            "run": row["name"],
            "owner": owner_identity(),
            "policy": {
                "retry_failed": retry_failed,
                "retry_uncertain": retry_uncertain,
                "reason": reason,
            },
            "before": plan,
            "exact_replay": False if retry_uncertain else None,
        },
    )
    session.mark("backing_up")
    try:
        # Complete all backups before touching any graph, including multi-paper runs.
        backups = {}
        for graph in plan["graphs"]:
            source_path = graph["path"]
            if source_path in backups:
                continue
            destination = folder / ("graph-" + str(len(backups)) + ".sqlite3")
            with durable_sqlite_reader(source_path, timeout_seconds=5) as source:
                with durable_sqlite_connection(
                    destination, timeout_seconds=5
                ) as target:
                    source.backup(target)
            destination.chmod(0o600)
            backups[source_path] = str(destination)
        session.mark("preparing", backups=backups)
        changed = []
        for graph in plan["graphs"]:
            store = SQLiteResearchGraphExecutionStore(graph["path"])
            try:
                cut = graph["cut_id"]
                active = store.active_cut(graph["logical_execution_id"])
                if active is None or active.cut_id != cut:
                    raise ValueError(
                        "active execution cut changed while recovery was prepared"
                    )
                snapshot = store.snapshot(cut)
                preserved = {
                    n.node_id: n
                    for n in snapshot.nodes
                    if n.state in (State.SUCCEEDED, State.REUSED)
                }
                store.recover_expired(cut, now_ns=time.time_ns())
                snapshot = store.snapshot(cut)
                if any(
                    n.state in (State.RUNNING, State.CLAIMED) for n in snapshot.nodes
                ):
                    raise ValueError("an execution lease became active during recovery")
                for node in snapshot.nodes:
                    if node.state is State.RECONCILE_REQUIRED:
                        if not retry_uncertain:
                            raise ValueError(
                                "new reconciliation debt requires explicit recovery"
                            )
                        moment = time.time_ns()
                        store.resolve_reconciliation(
                            cut,
                            node.node_id,
                            disposition=Disposition.RETRY,
                            now_ns=moment,
                            retry_not_before_ns=moment,
                        )
                        changed.append(
                            {
                                "cut": cut,
                                "node": node.node_id,
                                "action": "authorized_uncertain_retry",
                            }
                        )
                snapshot = store.snapshot(cut)
                for node in snapshot.nodes:
                    if node.state is State.FAILED:
                        if not retry_failed:
                            raise ValueError("new failed node requires --retry-failed")
                        store.retry_failed_subgraph(
                            cut,
                            node.node_id,
                            descendant_node_ids=_blocked_descendants(
                                store.snapshot(cut), node.node_id
                            ),
                            retry_not_before_ns=time.time_ns(),
                        )
                        changed.append(
                            {"cut": cut, "node": node.node_id, "action": "failed_retry"}
                        )
                snapshot = store.snapshot(cut)
                for node in snapshot.nodes:
                    control = store.node_control_state(cut, node.node_id)
                    if control.phase is NodePhase.RECOVERY_REQUIRED:
                        store.settle_node_recovery(
                            cut,
                            node.node_id,
                            expected_generation=control.generation,
                            now_ns=time.time_ns(),
                        )
                        control = store.node_control_state(cut, node.node_id)
                    if (
                        node.state in (State.READY, State.RETRY_WAIT)
                        and control.phase is NodePhase.PAUSED
                    ):
                        store.resume_node(
                            cut,
                            node.node_id,
                            expected_generation=control.generation,
                            now_ns=time.time_ns(),
                        )
                control = store.control_state(cut)
                if control.phase is Phase.RECOVERY_REQUIRED:
                    store.settle_recovery(
                        cut,
                        expected_generation=control.generation,
                        now_ns=time.time_ns(),
                    )
                after = store.snapshot(cut)
                if any(after.node(key) != value for key, value in preserved.items()):
                    raise RuntimeError("recovery altered a successful node")
            finally:
                store.close()
        session.mark("prepared", changed=changed)
        return session
    except BaseException as exc:
        session.mark("interrupted", error_type=type(exc).__name__)
        raise
