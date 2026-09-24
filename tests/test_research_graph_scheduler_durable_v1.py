from __future__ import annotations

import pytest

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_graph import (
    ResearchGraphNodeControlHalt,
    ResearchGraphScheduler,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphExecutionConflict,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeControlPhase,
    ResearchGraphNode,
    ResearchGraphNodeExecutorPort,
    ResearchGraphPlan,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


_FAR_FUTURE_NS = (1 << 63) - 1


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
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        _plan(),
        first_executor,
        execution_pool=pool,
        execution_store=store,
        execution_id="execution-1",
        lease_seconds=5.0,
    )
    try:
        report = scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert report.succeeded_node_ids == ("a", "b", "x")
    assert set(first_executor.calls) == {"a", "b", "x"}

    second_executor = _Executor()
    second_pool = _pool()
    resumed = ResearchGraphScheduler(
        _plan(),
        second_executor,
        execution_pool=second_pool,
        execution_store=store,
        execution_id="execution-1",
        lease_seconds=5.0,
    )
    try:
        second_report = resumed.execute()
    finally:
        resumed.close()
        second_pool.close()

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
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        execution_store=store,
        execution_id="execution-2",
        lease_seconds=5.0,
    )
    try:
        with pytest.raises(ResearchGraphNodeControlHalt) as captured:
            scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert tuple(row.node_id for row in captured.value.controls) == ("a",)
    assert captured.value.controls[0].phase is (
        ResearchGraphNodeControlPhase.RECOVERY_REQUIRED
    )
    assert executor.calls == ["x"]
    snapshot = store.snapshot("execution-2")
    assert snapshot.node("a").state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED
    assert snapshot.node("b").state is ResearchGraphLiveNodeState.PENDING
    assert snapshot.node("x").state is ResearchGraphLiveNodeState.SUCCEEDED



def test_paused_selected_node_is_not_claimed(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    plan = _plan()
    store.ensure_execution("execution-paused-selection", plan)
    control = store.node_control_state("execution-paused-selection", "a")
    paused = store.pause_node_if_quiescent(
        "execution-paused-selection",
        "a",
        expected_generation=control.generation,
        now_ns=1,
    )
    assert paused.phase is ResearchGraphNodeControlPhase.PAUSED

    executor = _Executor()
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        execution_store=store,
        execution_id="execution-paused-selection",
        selected_node_ids=("a",),
    )
    try:
        with pytest.raises(ResearchGraphNodeControlHalt) as captured:
            scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert tuple(row.node_id for row in captured.value.controls) == ("a",)
    assert captured.value.controls[0].phase is ResearchGraphNodeControlPhase.PAUSED
    assert executor.calls == []
    assert store.attempts("execution-paused-selection", "a") == ()


def test_local_recovery_debt_does_not_stop_independent_branch(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    plan = _plan()
    store.ensure_execution("execution-local-recovery", plan)
    store.mark_ready("execution-local-recovery", "a", now_ns=1)
    claim = store.claim(
        "execution-local-recovery",
        "a",
        owner_id="scheduler-old",
        now_ns=2,
        lease_expires_at_ns=_FAR_FUTURE_NS,
    )
    store.mark_running(
        "execution-local-recovery",
        "a",
        attempt_id=claim.attempt_id or "",
        owner_id="scheduler-old",
        now_ns=3,
    )
    control = store.node_control_state("execution-local-recovery", "a")
    interrupted = store.interrupt_node(
        "execution-local-recovery",
        "a",
        expected_generation=control.generation,
        now_ns=4,
    )
    assert interrupted.phase is ResearchGraphNodeControlPhase.RECOVERY_REQUIRED

    executor = _Executor()
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        execution_store=store,
        execution_id="execution-local-recovery",
    )
    try:
        with pytest.raises(ResearchGraphNodeControlHalt) as captured:
            scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert executor.calls == ["x"]
    assert tuple(row.node_id for row in captured.value.controls) == ("a",)
    snapshot = store.snapshot("execution-local-recovery")
    assert snapshot.node("a").state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED
    assert snapshot.node("b").state is ResearchGraphLiveNodeState.PENDING
    assert snapshot.node("x").state is ResearchGraphLiveNodeState.SUCCEEDED


def test_disjoint_selection_runs_while_unrelated_node_has_live_lease(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    plan = _plan()
    store.ensure_execution("execution-disjoint", plan)
    store.mark_ready("execution-disjoint", "a", now_ns=1)
    claim = store.claim(
        "execution-disjoint",
        "a",
        owner_id="scheduler-a",
        now_ns=2,
        lease_expires_at_ns=_FAR_FUTURE_NS,
    )
    store.mark_running(
        "execution-disjoint",
        "a",
        attempt_id=claim.attempt_id or "",
        owner_id="scheduler-a",
        now_ns=3,
    )

    executor = _Executor()
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        execution_store=store,
        execution_id="execution-disjoint",
        selected_node_ids=("x",),
    )
    try:
        report = scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert report.succeeded_node_ids == ("x",)
    assert executor.calls == ["x"]
    snapshot = store.snapshot("execution-disjoint")
    assert snapshot.node("a").state is ResearchGraphLiveNodeState.RUNNING
    assert snapshot.node("x").state is ResearchGraphLiveNodeState.SUCCEEDED


def test_overlapping_selection_rejects_live_lease(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    plan = _plan()
    store.ensure_execution("execution-overlap", plan)
    store.mark_ready("execution-overlap", "a", now_ns=1)
    claim = store.claim(
        "execution-overlap",
        "a",
        owner_id="scheduler-a",
        now_ns=2,
        lease_expires_at_ns=_FAR_FUTURE_NS,
    )
    store.mark_running(
        "execution-overlap",
        "a",
        attempt_id=claim.attempt_id or "",
        owner_id="scheduler-a",
        now_ns=3,
    )

    executor = _Executor()
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        execution_store=store,
        execution_id="execution-overlap",
        selected_node_ids=("a",),
    )
    try:
        with pytest.raises(
            ResearchGraphExecutionConflict,
            match="active non-expired leases",
        ):
            scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert executor.calls == []
