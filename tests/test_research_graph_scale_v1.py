from __future__ import annotations

from collections import Counter
from threading import RLock

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_graph import ResearchGraphScheduler
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphNode,
    ResearchGraphPlan,
)


class _DependencyCheckingExecutor:
    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.completed: set[str] = set()
        self._lock = RLock()

    def execute(self, context, node, *, deadline) -> None:
        del deadline
        context.checkpoint()
        with self._lock:
            missing = tuple(
                dependency
                for dependency in node.depends_on_node_ids
                if dependency not in self.completed
            )
            if missing:
                raise AssertionError(
                    f"node {node.node_id} started before dependencies completed: {missing}"
                )
            self.calls[node.node_id] += 1
            if self.calls[node.node_id] != 1:
                raise AssertionError(
                    f"node executed more than once: {node.node_id}"
                )
            self.completed.add(node.node_id)
        context.checkpoint()


def _node(node_id: str, *dependencies: str) -> ResearchGraphNode:
    return ResearchGraphNode(
        node_id,
        canonical_digest({"research_graph_scale_node": node_id}),
        tuple(dependencies),
    )


def _scale_plan() -> ResearchGraphPlan:
    nodes: list[ResearchGraphNode] = []
    paper_tails: list[str] = []

    for paper_index in range(4):
        prefix = f"paper-{paper_index}"
        root = f"{prefix}:root"
        nodes.append(_node(root))

        width = tuple(f"{prefix}:experiment-{index}" for index in range(8))
        nodes.extend(_node(node_id, root) for node_id in width)

        fan_in = f"{prefix}:fan-in"
        nodes.append(_node(fan_in, *width))

        previous = fan_in
        for depth in range(20):
            current = f"{prefix}:deep-{depth:02d}"
            nodes.append(_node(current, previous))
            previous = current
        paper_tails.append(previous)

    nodes.append(_node("portfolio:final-fan-in", *paper_tails))
    assert len(nodes) == 121
    return ResearchGraphPlan(
        "scale-4-papers-121-nodes",
        canonical_digest({"revision": "scale-4-papers-121-nodes"}),
        tuple(nodes),
    )


def _pool() -> ResearchExecutionPool:
    return ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=8,
            max_blocking_io_in_flight=16,
            max_cpu_workers=1,
            max_cpu_in_flight=1,
            max_async_io_in_flight=8,
        ),
        experiment_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_blocking_io_in_flight=4,
            max_cpu_workers=1,
            max_cpu_in_flight=1,
            max_async_io_in_flight=2,
        ),
    )


def test_research_graph_executes_121_node_multi_paper_dag_exactly_once() -> None:
    plan = _scale_plan()
    executor = _DependencyCheckingExecutor()
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        task_group_id="scale-4-papers-121-nodes",
    )
    try:
        report = scheduler.execute()
        admission = pool.orchestration_admission_snapshot()
    finally:
        scheduler.close()
        pool.close()

    assert report.failed_node_ids == ()
    assert report.blocked_node_ids == ()
    assert report.cancelled_node_ids == ()
    assert len(report.succeeded_node_ids) == 121
    assert set(report.succeeded_node_ids) == {node.node_id for node in plan.nodes}
    assert executor.calls == Counter({node.node_id: 1 for node in plan.nodes})
    assert executor.completed == {node.node_id for node in plan.nodes}
    assert admission.in_flight == 0
    assert admission.waiting == 0


def test_research_graph_executes_128_node_deep_chain_in_dependency_order() -> None:
    node_ids = tuple(f"deep-chain-{index:03d}" for index in range(128))
    nodes = tuple(
        _node(
            node_id,
            *(() if index == 0 else (node_ids[index - 1],)),
        )
        for index, node_id in enumerate(node_ids)
    )
    plan = ResearchGraphPlan(
        "scale-deep-chain-128",
        canonical_digest({"revision": "scale-deep-chain-128"}),
        nodes,
    )
    executor = _DependencyCheckingExecutor()
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        task_group_id="scale-deep-chain-128",
    )
    try:
        report = scheduler.execute()
        admission = pool.orchestration_admission_snapshot()
    finally:
        scheduler.close()
        pool.close()

    assert report.failed_node_ids == ()
    assert report.blocked_node_ids == ()
    assert report.cancelled_node_ids == ()
    assert report.succeeded_node_ids == tuple(sorted(node_ids))
    assert executor.calls == Counter({node_id: 1 for node_id in node_ids})
    assert executor.completed == set(node_ids)
    assert admission.in_flight == 0
    assert admission.waiting == 0


def test_scale_failure_isolated_to_one_paper_descendant_closure() -> None:
    plan = _scale_plan()
    failing_node = "paper-2:experiment-3"

    class _FailingExecutor(_DependencyCheckingExecutor):
        def execute(self, context, node, *, deadline) -> None:
            if node.node_id == failing_node:
                context.checkpoint()
                with self._lock:
                    missing = tuple(
                        dependency
                        for dependency in node.depends_on_node_ids
                        if dependency not in self.completed
                    )
                    if missing:
                        raise AssertionError(
                            f"failing node started before dependencies completed: {missing}"
                        )
                    self.calls[node.node_id] += 1
                raise RuntimeError("injected scale failure")
            super().execute(context, node, deadline=deadline)

    executor = _FailingExecutor()
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        task_group_id="scale-failure-isolation",
    )
    try:
        report = scheduler.execute()
        admission = pool.orchestration_admission_snapshot()
    finally:
        scheduler.close()
        pool.close()

    by_id = {row.node_id: row for row in report.nodes}
    assert report.failed_node_ids == (failing_node,)
    assert by_id["paper-2:fan-in"].state.value == "blocked"
    assert by_id["paper-2:deep-00"].state.value == "blocked"
    assert by_id["paper-2:deep-19"].state.value == "blocked"
    assert "paper-2:fan-in" not in executor.calls
    assert "paper-2:deep-00" not in executor.calls

    for paper_index in (0, 1, 3):
        tail = f"paper-{paper_index}:deep-19"
        assert by_id[tail].state.value == "succeeded"
        assert executor.calls[tail] == 1

    assert by_id["portfolio:final-fan-in"].state.value == "blocked"
    assert "portfolio:final-fan-in" not in executor.calls
    assert admission.in_flight == 0
    assert admission.waiting == 0
