from __future__ import annotations

from threading import RLock
import time

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_graph import ResearchGraphScheduler
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphNode,
    ResearchGraphNodeState,
    ResearchGraphPlan,
)


class _Executor:
    def __init__(self, *, failing: frozenset[str] = frozenset()) -> None:
        self.failing = failing
        self.events: dict[str, float] = {}
        self._lock = RLock()

    def execute(self, context, node, *, deadline) -> None:
        del deadline
        context.checkpoint()
        with self._lock:
            self.events[f"{node.node_id}.start"] = time.monotonic()
        if node.node_id == "slow":
            time.sleep(0.03)
        if node.node_id in self.failing:
            raise RuntimeError(f"injected failure: {node.node_id}")
        with self._lock:
            self.events[f"{node.node_id}.end"] = time.monotonic()


def _pool() -> ResearchExecutionPool:
    return ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=4,
            max_cpu_workers=1,
            max_async_io_in_flight=4,
        ),
        experiment_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        ),
    )


def test_research_graph_releases_fan_in_only_after_all_dependencies_succeed() -> None:
    plan = ResearchGraphPlan(
        "fan-in",
        "a" * 64,
        (
            ResearchGraphNode("fast", "1" * 64),
            ResearchGraphNode("slow", "2" * 64),
            ResearchGraphNode("join", "3" * 64, ("fast", "slow")),
        ),
    )
    executor = _Executor()
    pool = _pool()
    scheduler = ResearchGraphScheduler(plan, executor, execution_pool=pool)
    try:
        report = scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert report.succeeded_node_ids == ("fast", "join", "slow")
    assert report.failed_node_ids == ()
    assert report.blocked_node_ids == ()
    assert executor.events["join.start"] >= executor.events["fast.end"]
    assert executor.events["join.start"] >= executor.events["slow.end"]
    assert executor.events["fast.start"] < executor.events["slow.end"]


def test_research_graph_failure_blocks_only_descendants() -> None:
    plan = ResearchGraphPlan(
        "failure-isolation",
        "b" * 64,
        (
            ResearchGraphNode("root", "1" * 64),
            ResearchGraphNode("child", "2" * 64, ("root",)),
            ResearchGraphNode("grandchild", "3" * 64, ("child",)),
            ResearchGraphNode("independent", "4" * 64),
        ),
    )
    executor = _Executor(failing=frozenset({"root"}))
    pool = _pool()
    scheduler = ResearchGraphScheduler(plan, executor, execution_pool=pool)
    try:
        report = scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    by_id = {row.node_id: row for row in report.nodes}
    assert by_id["root"].state is ResearchGraphNodeState.FAILED
    assert by_id["child"].state is ResearchGraphNodeState.BLOCKED
    assert by_id["child"].blocked_by_node_ids == ("root",)
    assert by_id["grandchild"].state is ResearchGraphNodeState.BLOCKED
    assert by_id["grandchild"].blocked_by_node_ids == ("child",)
    assert by_id["independent"].state is ResearchGraphNodeState.SUCCEEDED
    assert "child.start" not in executor.events
    assert "grandchild.start" not in executor.events
    assert "independent.end" in executor.events


def test_research_graph_plan_rejects_cycles_before_execution() -> None:
    try:
        ResearchGraphPlan(
            "cycle",
            "c" * 64,
            (
                ResearchGraphNode("a", "1" * 64, ("b",)),
                ResearchGraphNode("b", "2" * 64, ("a",)),
            ),
        )
    except ValueError as exc:
        assert "dependency cycle" in str(exc)
    else:
        raise AssertionError("research graph cycle was accepted")
