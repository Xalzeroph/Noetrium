from __future__ import annotations

import pytest

from noetrium_platform.composition.research_graph import ResearchGraphScheduler
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphLiveNodeState,
    ResearchGraphNode,
    ResearchGraphNodeExecutorPort,
    ResearchGraphPlan,
    ResearchGraphReconciliationRequired,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


class _Executor(ResearchGraphNodeExecutorPort):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, context, node, *, deadline) -> None:
        self.calls.append(node.node_id)


def _plan() -> ResearchGraphPlan:
    a = ResearchGraphNode("a", canonical_digest({"node": "a"}))
    b = ResearchGraphNode(
        "b",
        canonical_digest({"node": "b"}),
        ("a",),
    )
    x = ResearchGraphNode("x", canonical_digest({"node": "x"}))
    return ResearchGraphPlan(
        "durable-scheduler",
        canonical_digest({"revision": "r1"}),
        (a, b, x),
    )


def test_durable_scheduler_reuses_completed_graph_without_reexecution(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    first_executor = _Executor()
    scheduler = ResearchGraphScheduler(
        _plan(),
        first_executor,
        execution_store=store,
        execution_id="execution-1",
        lease_seconds=5.0,
    )
    try:
        report = scheduler.execute()
    finally:
        scheduler.close()

    assert report.succeeded_node_ids == ("a", "b", "x")
    assert set(first_executor.calls) == {"a", "b", "x"}

    second_executor = _Executor()
    resumed = ResearchGraphScheduler(
        _plan(),
        second_executor,
        execution_store=store,
        execution_id="execution-1",
        lease_seconds=5.0,
    )
    try:
        second_report = resumed.execute()
    finally:
        resumed.close()

    assert second_report.succeeded_node_ids == ("a", "b", "x")
    assert second_executor.calls == []


def test_durable_scheduler_runs_unrelated_branch_before_reconciliation_boundary(
    tmp_path,
) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    plan = _plan()
    store.ensure_execution("execution-2", plan)
    store.mark_ready("execution-2", "a", now_ns=0)
    claim = store.claim(
        "execution-2",
        "a",
        owner_id="dead-scheduler",
        now_ns=0,
        lease_expires_at_ns=1,
    )
    store.mark_running(
        "execution-2",
        "a",
        attempt_id=claim.attempt_id or "",
        owner_id="dead-scheduler",
        now_ns=0,
    )

    executor = _Executor()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_store=store,
        execution_id="execution-2",
        lease_seconds=5.0,
    )
    try:
        with pytest.raises(ResearchGraphReconciliationRequired) as captured:
            scheduler.execute()
    finally:
        scheduler.close()

    assert captured.value.node_ids == ("a",)
    assert executor.calls == ["x"]
    snapshot = store.snapshot("execution-2")
    assert snapshot.node("a").state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED
    assert snapshot.node("b").state is ResearchGraphLiveNodeState.PENDING
    assert snapshot.node("x").state is ResearchGraphLiveNodeState.SUCCEEDED
