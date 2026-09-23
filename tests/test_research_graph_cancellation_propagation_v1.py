from __future__ import annotations

from pathlib import Path

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_graph import ResearchGraphScheduler
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphLiveNodeState,
    ResearchGraphNode,
    ResearchGraphNodeState,
    ResearchGraphPlan,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


class _NeverExecute:
    def execute(self, context, node, *, deadline) -> None:
        del context, node, deadline
        raise AssertionError("cancelled dependency graph must not execute downstream work")


def _pool() -> ResearchExecutionPool:
    return ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        )
    )


def test_cancelled_dependency_blocks_downstream_in_durable_scheduler(
    tmp_path: Path,
) -> None:
    plan = ResearchGraphPlan(
        "cancel-propagation",
        canonical_digest({"revision": 1}),
        (
            ResearchGraphNode(
                "a",
                canonical_digest({"node": "a"}),
            ),
            ResearchGraphNode(
                "b",
                canonical_digest({"node": "b"}),
                ("a",),
            ),
        ),
    )
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    snapshot = store.ensure_execution("execution", plan)
    control = store.node_control_state("execution", "a")
    store.cancel_node_subgraph(
        "execution",
        "a",
        descendant_node_ids=(),
        expected_generation=control.generation,
        now_ns=1,
    )

    pool = _pool()
    scheduler = ResearchGraphScheduler(
        plan,
        _NeverExecute(),
        execution_pool=pool,
        execution_store=store,
        execution_id="execution",
    )
    try:
        report = scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    results = {row.node_id: row for row in report.nodes}
    assert results["a"].state is ResearchGraphNodeState.CANCELLED
    assert results["b"].state is ResearchGraphNodeState.BLOCKED
    assert results["b"].blocked_by_node_ids == ("a",)

    durable = store.snapshot(snapshot.execution_id)
    assert durable.node("a").state is ResearchGraphLiveNodeState.CANCELLED
    assert durable.node("b").state is ResearchGraphLiveNodeState.BLOCKED
    assert durable.node("b").blocked_by_node_ids == ("a",)
    assert store.attempts(snapshot.execution_id, "a") == ()
    assert store.attempts(snapshot.execution_id, "b") == ()
