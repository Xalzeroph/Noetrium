from __future__ import annotations

from resource_test_support import make_execution_pool

from tests._execution_graph_fixtures import scheduling_vertex as ResearchSchedulingNode, scheduling_graph as ResearchSchedulingPlan

from pathlib import Path
import tempfile
from threading import RLock
import time

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_graph import ResearchGraphScheduler
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.research.execution.graph.providers.sqlite import SQLiteResearchGraphExecutionStore
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphNodeState,
    execution_graph_id,
    execution_vertex_id,
)



def _graph_store(label: str) -> SQLiteResearchGraphExecutionStore:
    root = Path(tempfile.mkdtemp(prefix=f"noetrium-{label}-"))
    return SQLiteResearchGraphExecutionStore(root / "research-graph.sqlite3")


class _Executor:
    def __init__(self, *, failing: frozenset[str] = frozenset()) -> None:
        self.failing = failing
        self.events: dict[str, float] = {}
        self._lock = RLock()

    def execute(self, context, node, *, deadline) -> None:
        del deadline
        context.checkpoint()
        node_id = execution_vertex_id(node)
        with self._lock:
            self.events[f"{node_id}.start"] = time.monotonic()
        if node_id == "slow":
            time.sleep(0.03)
        if node_id in self.failing:
            raise RuntimeError(f"injected failure: {node_id}")
        with self._lock:
            self.events[f"{node_id}.end"] = time.monotonic()


def _pool() -> ResearchExecutionPool:
    return make_execution_pool(
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
    plan = ResearchSchedulingPlan(
        "fan-in",
        "a" * 64,
        (
            ResearchSchedulingNode("fast", "1" * 64),
            ResearchSchedulingNode("slow", "2" * 64),
            ResearchSchedulingNode("join", "3" * 64, ("fast", "slow")),
        ),
    )
    executor = _Executor()
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        execution_store=_graph_store(execution_graph_id(plan)),
        execution_id=f"test:{execution_graph_id(plan)}",
    )
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
    plan = ResearchSchedulingPlan(
        "failure-isolation",
        "b" * 64,
        (
            ResearchSchedulingNode("root", "1" * 64),
            ResearchSchedulingNode("child", "2" * 64, ("root",)),
            ResearchSchedulingNode("grandchild", "3" * 64, ("child",)),
            ResearchSchedulingNode("independent", "4" * 64),
        ),
    )
    executor = _Executor(failing=frozenset({"root"}))
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        execution_store=_graph_store(execution_graph_id(plan)),
        execution_id=f"test:{execution_graph_id(plan)}",
    )
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


def test_research_graph_prioritizes_cheap_pure_work_before_effects() -> None:
    plan = ResearchSchedulingPlan(
        "cost-aware",
        "d" * 64,
        (
            ResearchSchedulingNode(
                "a-effect",
                "1" * 64,
                effectful=True,
                static_cost=1,
            ),
            ResearchSchedulingNode(
                "b-pure-expensive",
                "2" * 64,
                static_cost=9,
            ),
            ResearchSchedulingNode(
                "c-pure-cheap",
                "3" * 64,
                static_cost=1,
            ),
        ),
    )
    executor = _Executor()
    pool = make_execution_pool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            max_async_io_in_flight=1,
        ),
        experiment_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            max_async_io_in_flight=1,
        ),
    )
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        execution_store=_graph_store(execution_graph_id(plan)),
        execution_id=f"test:{execution_graph_id(plan)}",
    )
    try:
        report = scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert report.failed_node_ids == ()
    starts = tuple(
        node_id
        for node_id, _when in sorted(
            (
                (key.removesuffix(".start"), when)
                for key, when in executor.events.items()
                if key.endswith(".start")
            ),
            key=lambda row: row[1],
        )
    )
    assert starts == (
        "c-pure-cheap",
        "b-pure-expensive",
        "a-effect",
    )


def test_research_graph_plan_rejects_cycles_before_execution() -> None:
    try:
        ResearchSchedulingPlan(
            "cycle",
            "c" * 64,
            (
                ResearchSchedulingNode("a", "1" * 64, ("b",)),
                ResearchSchedulingNode("b", "2" * 64, ("a",)),
            ),
        )
    except ValueError as exc:
        assert "dependency cycle" in str(exc)
    else:
        raise AssertionError("research graph cycle was accepted")

def test_research_graph_prioritizes_longer_remaining_critical_path() -> None:
    plan = ResearchSchedulingPlan(
        "critical-path",
        "e" * 64,
        (
            ResearchSchedulingNode(
                "short",
                "1" * 64,
                static_cost=1,
            ),
            ResearchSchedulingNode(
                "long-root",
                "2" * 64,
                static_cost=1,
            ),
            ResearchSchedulingNode(
                "long-tail",
                "3" * 64,
                ("long-root",),
                static_cost=9,
            ),
        ),
    )
    executor = _Executor()
    pool = make_execution_pool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            max_async_io_in_flight=1,
        ),
        experiment_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            max_async_io_in_flight=1,
        ),
    )
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        execution_store=_graph_store(execution_graph_id(plan)),
        execution_id=f"test:{execution_graph_id(plan)}",
    )
    try:
        report = scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert report.failed_node_ids == ()
    starts = tuple(
        node_id
        for node_id, _when in sorted(
            (
                (key.removesuffix(".start"), when)
                for key, when in executor.events.items()
                if key.endswith(".start")
            ),
            key=lambda row: row[1],
        )
    )
    # "short" has the lexicographically earlier digest/ticket. The scheduler
    # must still choose the branch with 1 + 9 remaining work first.
    assert starts[0] == "long-root"
