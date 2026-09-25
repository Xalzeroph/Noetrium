from __future__ import annotations

from contextlib import contextmanager

import pytest

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_graph import ResearchGraphScheduler
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphExecutionConflict,
    ResearchGraphLiveNodeState,
    ResearchGraphNode,
    ResearchGraphPlan,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


def _node(node_id: str, *depends_on: str) -> ResearchGraphNode:
    return ResearchGraphNode(
        node_id,
        canonical_digest({"node": node_id}),
        tuple(depends_on),
    )


def _plan(nodes: tuple[ResearchGraphNode, ...]) -> ResearchGraphPlan:
    return ResearchGraphPlan(
        "batch-state-fixture",
        canonical_digest({
            "revision": "batch-state-fixture",
            "nodes": tuple(node.node_id for node in nodes),
        }),
        nodes,
    )


class _CountingStore(SQLiteResearchGraphExecutionStore):
    def __init__(self, path) -> None:
        super().__init__(path)
        self.transaction_count = 0
        self.single_node_read_count = 0

    @contextmanager
    def _transaction(self):
        self.transaction_count += 1
        with super()._transaction() as conn:
            yield conn

    def _node_tx(self, conn, execution_id, node_id):
        self.single_node_read_count += 1
        return super()._node_tx(conn, execution_id, node_id)


def test_ready_and_blocked_batches_use_one_transaction_and_generation_each(
    tmp_path,
) -> None:
    nodes = tuple(_node(f"n-{index:03d}") for index in range(64))
    plan = _plan(nodes)
    store = _CountingStore(tmp_path / "graph.sqlite3")
    initial = store.ensure_execution("execution", plan)

    store.transaction_count = 0
    ready = store.mark_ready_many(
        "execution",
        tuple(node.node_id for node in nodes),
        now_ns=10,
    )
    after_ready = store.snapshot("execution")
    assert store.transaction_count == 1
    assert store.single_node_read_count == 0
    assert after_ready.generation == initial.generation + 1
    assert len(ready) == 64
    assert {
        row.state for row in ready
    } == {ResearchGraphLiveNodeState.READY}

    store.transaction_count = 0
    blockers = tuple(
        (node.node_id, ("cause",))
        for node in nodes
    )
    blocked = store.mark_blocked_many("execution", blockers)
    after_blocked = store.snapshot("execution")
    assert store.transaction_count == 1
    assert store.single_node_read_count == 0
    assert after_blocked.generation == after_ready.generation + 1
    assert len(blocked) == 64
    assert {
        row.state for row in blocked
    } == {ResearchGraphLiveNodeState.BLOCKED}


def test_ready_batch_rolls_back_all_rows_when_one_transition_is_invalid(
    tmp_path,
) -> None:
    nodes = (_node("a"), _node("b"))
    plan = _plan(nodes)
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    before = store.ensure_execution("execution", plan)

    with pytest.raises(Exception):
        store.mark_ready_many(
            "execution",
            ("a", "missing"),
            now_ns=10,
        )

    after = store.snapshot("execution")
    assert after.generation == before.generation
    assert after.node("a").state is ResearchGraphLiveNodeState.PENDING
    assert after.node("b").state is ResearchGraphLiveNodeState.PENDING


class _BatchOnlyStore(SQLiteResearchGraphExecutionStore):
    def mark_ready(self, *args, **kwargs):
        raise AssertionError("scheduler used single-node mark_ready")

    def mark_blocked(self, *args, **kwargs):
        raise AssertionError("scheduler used single-node mark_blocked")


class _FailRootExecutor:
    def execute(self, context, node, *, deadline) -> None:
        del deadline
        context.checkpoint()
        if node.node_id == "root":
            raise RuntimeError("injected root failure")
        context.checkpoint()


def test_durable_scheduler_uses_batch_transition_authority(tmp_path) -> None:
    nodes = (
        _node("root"),
        _node("left", "root"),
        _node("right", "root"),
        _node("independent"),
    )
    plan = _plan(nodes)
    store = _BatchOnlyStore(tmp_path / "graph.sqlite3")
    pool = ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_blocking_io_in_flight=2,
            max_async_io_in_flight=2,
            max_cpu_workers=1,
            max_cpu_in_flight=1,
        ),
    )
    scheduler = ResearchGraphScheduler(
        plan,
        _FailRootExecutor(),
        execution_pool=pool,
        execution_store=store,
        execution_id="execution",
    )
    try:
        report = scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    by_id = {row.node_id: row for row in report.nodes}
    assert by_id["root"].state.value == "failed"
    assert by_id["left"].state.value == "blocked"
    assert by_id["right"].state.value == "blocked"
    assert by_id["independent"].state.value == "succeeded"
