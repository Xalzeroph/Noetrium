from __future__ import annotations

from resource_test_support import make_execution_pool

from tests._execution_graph_fixtures import materialize_execution as _materialize_execution

from tests._execution_graph_fixtures import scheduling_vertex as ResearchSchedulingNode, scheduling_graph as ResearchSchedulingPlan

from threading import Event, Thread

import pytest

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_graph import (
    ResearchGraphControlHalt,
    ResearchGraphNodeControlHalt,
    ResearchGraphScheduler,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphControlPhase,
    ResearchGraphExecutionConflict,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeControlPhase,
    ResearchGraphNodeExecutorPort,
    execution_vertex_id,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


_FAR_FUTURE_NS = (1 << 63) - 1


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


class _Executor(ResearchGraphNodeExecutorPort):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, context, node, *, deadline) -> None:
        self.calls.append(execution_vertex_id(node))


def _plan() -> ResearchSchedulingPlan:
    a = ResearchSchedulingNode("a", canonical_digest({"node": "a"}))
    b = ResearchSchedulingNode(
        "b",
        canonical_digest({"node": "b"}),
        ("a",),
    )
    x = ResearchSchedulingNode("x", canonical_digest({"node": "x"}))
    return ResearchSchedulingPlan(
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
    _materialize_execution(store, "execution-2", plan)
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
    _materialize_execution(store, "execution-paused-selection", plan)
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
    _materialize_execution(store, "execution-local-recovery", plan)
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
    _materialize_execution(store, "execution-disjoint", plan)
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
    _materialize_execution(store, "execution-overlap", plan)
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


class _FailOnceExecutor(_Executor):
    def __init__(self, failing_node_id: str) -> None:
        super().__init__()
        self._failing_node_id = failing_node_id
        self._failed = False

    def execute(self, context, node, *, deadline) -> None:
        node_id = execution_vertex_id(node)
        self.calls.append(node_id)
        if node_id == self._failing_node_id and not self._failed:
            self._failed = True
            raise RuntimeError("injected retryable failure")


def test_retry_failed_subgraph_reruns_only_failed_root_and_descendants(
    tmp_path,
) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    plan = _plan()
    first_executor = _FailOnceExecutor("a")
    first_pool = _pool()
    first = ResearchGraphScheduler(
        plan,
        first_executor,
        execution_pool=first_pool,
        execution_store=store,
        execution_id="execution-retry-subgraph",
    )
    try:
        first_report = first.execute()
    finally:
        first.close()
        first_pool.close()

    assert first_report.failed_node_ids == ("a",)
    assert first_report.blocked_node_ids == ("b",)
    assert first_report.succeeded_node_ids == ("x",)
    assert first_executor.calls.count("a") == 1
    assert first_executor.calls.count("x") == 1
    assert first_executor.calls.count("b") == 0
    assert len(store.attempts("execution-retry-subgraph", "a")) == 1
    assert len(store.attempts("execution-retry-subgraph", "x")) == 1

    retried = store.retry_failed_subgraph(
        "execution-retry-subgraph",
        "a",
        descendant_node_ids=("b",),
        retry_not_before_ns=0,
    )
    assert retried.node("a").state is ResearchGraphLiveNodeState.RETRY_WAIT
    assert retried.node("b").state is ResearchGraphLiveNodeState.PENDING
    assert retried.node("x").state is ResearchGraphLiveNodeState.SUCCEEDED

    resumed_executor = _Executor()
    resumed_pool = _pool()
    resumed = ResearchGraphScheduler(
        plan,
        resumed_executor,
        execution_pool=resumed_pool,
        execution_store=store,
        execution_id="execution-retry-subgraph",
    )
    try:
        final_report = resumed.execute()
    finally:
        resumed.close()
        resumed_pool.close()

    assert final_report.succeeded_node_ids == ("a", "b", "x")
    assert final_report.failed_node_ids == ()
    assert final_report.blocked_node_ids == ()
    assert resumed_executor.calls == ["a", "b"]
    assert len(store.attempts("execution-retry-subgraph", "a")) == 2
    assert len(store.attempts("execution-retry-subgraph", "b")) == 1
    assert len(store.attempts("execution-retry-subgraph", "x")) == 1


def test_graph_interrupt_cancels_inflight_task_context_and_converges(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    node = ResearchSchedulingNode("a", canonical_digest({"node": "a"}))
    plan = ResearchSchedulingPlan(
        "interrupt-live",
        canonical_digest({"revision": "r1"}),
        (node,),
    )
    _materialize_execution(store, "execution-interrupt-live", plan)

    class BlockingExecutor(ResearchGraphNodeExecutorPort):
        def __init__(self) -> None:
            self.started = Event()
            self.stopped = Event()

        def execute(self, context, node, *, deadline) -> None:
            del node, deadline
            self.started.set()
            try:
                while True:
                    context.checkpoint()
                    self.stopped.wait(0.01)
            finally:
                self.stopped.set()

    executor = BlockingExecutor()
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        execution_store=store,
        execution_id="execution-interrupt-live",
    )
    failures: list[BaseException] = []

    def execute() -> None:
        try:
            scheduler.execute()
        except BaseException as exc:
            failures.append(exc)

    thread = Thread(target=execute, daemon=True)
    thread.start()
    assert executor.started.wait(timeout=2.0)

    control = store.control_state("execution-interrupt-live")
    interrupted = store.interrupt(
        "execution-interrupt-live",
        expected_generation=control.generation,
        now_ns=10,
    )
    assert interrupted.phase is ResearchGraphControlPhase.RECOVERY_REQUIRED

    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert executor.stopped.is_set()
    assert len(failures) == 1
    assert isinstance(failures[0], ResearchGraphControlHalt)
    assert failures[0].control.phase is ResearchGraphControlPhase.RECOVERY_REQUIRED

    scheduler.close()
    pool.close()


def test_draining_cut_transitions_to_paused_without_claiming_new_work(
    tmp_path,
) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    plan = _plan()
    _materialize_execution(store, "execution-draining", plan)
    control = store.control_state("execution-draining")
    draining = store.request_drain(
        "execution-draining",
        expected_generation=control.generation,
        now_ns=1,
    )
    assert draining.phase is ResearchGraphControlPhase.DRAINING

    executor = _Executor()
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        execution_store=store,
        execution_id="execution-draining",
    )
    try:
        with pytest.raises(ResearchGraphControlHalt) as captured:
            scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert captured.value.control.phase is ResearchGraphControlPhase.PAUSED
    assert executor.calls == []
    assert store.attempts("execution-draining", "a") == ()
    assert store.attempts("execution-draining", "b") == ()
    assert store.attempts("execution-draining", "x") == ()


def test_paused_cut_never_claims_new_work_until_explicit_resume(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    plan = _plan()
    _materialize_execution(store, "execution-paused", plan)
    control = store.control_state("execution-paused")
    paused = store.pause_if_quiescent(
        "execution-paused",
        expected_generation=control.generation,
        now_ns=1,
    )
    assert paused.phase is ResearchGraphControlPhase.PAUSED

    executor = _Executor()
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        execution_store=store,
        execution_id="execution-paused",
    )
    try:
        with pytest.raises(ResearchGraphControlHalt) as captured:
            scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert captured.value.control.phase is ResearchGraphControlPhase.PAUSED
    assert executor.calls == []
    assert store.attempts("execution-paused", "a") == ()
    assert store.attempts("execution-paused", "b") == ()
    assert store.attempts("execution-paused", "x") == ()


def test_wide_unit_frontier_marks_only_authority_admissible_top_k(
    tmp_path, monkeypatch,
) -> None:
    """A wide independent ready-set cannot produce a wide READY write batch.

    Dispatch picks the same ordered priority prefix and refills after child
    completions. Remaining Units retain their original pending semantics.
    """
    count = 32
    from noetrium_platform.composition.research_graph_frontier import (
        ResearchGraphDependencyFrontier,
    )

    def forbid_legacy_ready_scan(*args, **kwargs):
        raise AssertionError("legacy full-frontier selection is forbidden")

    monkeypatch.setattr(
        ResearchGraphDependencyFrontier,
        "next_ready_node_ids",
        forbid_legacy_ready_scan,
    )
    plan = ResearchSchedulingPlan(
        "wide-durable-unit-frontier",
        canonical_digest({"revision": "wide-frontier-top-k"}),
        tuple(
            ResearchSchedulingNode(
                f"unit-{index:03d}",
                canonical_digest({"unit": index}),
            )
            for index in range(count)
        ),
    )
    store = SQLiteResearchGraphExecutionStore(tmp_path / "wide.sqlite3")
    original_mark_ready = store.mark_ready_many
    ready_batch_sizes = []

    def mark_ready(execution_id, node_ids, *, now_ns):
        ready_batch_sizes.append(len(node_ids))
        return original_mark_ready(
            execution_id, node_ids, now_ns=now_ns,
        )

    monkeypatch.setattr(store, "mark_ready_many", mark_ready)
    executor = _Executor()
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        execution_store=store,
        execution_id="wide-unit-frontier",
    )
    try:
        report = scheduler.execute()
        assert len(report.succeeded_node_ids) == count
        assert set(executor.calls) == set(report.succeeded_node_ids)
        assert ready_batch_sizes
        # Admission is controlled by the one shared orchestration authority.
        budget = pool.orchestration_admission_snapshot()
        assert max(ready_batch_sizes) <= min(
            budget.max_total_in_flight,
            budget.max_in_flight_per_group,
            budget.max_in_flight_per_tenant,
            budget.max_in_flight_per_resource,
            next(lane.max_in_flight for lane in budget.lanes
                 if lane.lane_kind.name == "BLOCKING_IO"),
        )
    finally:
        scheduler.close()
        pool.close()
