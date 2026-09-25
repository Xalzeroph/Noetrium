from __future__ import annotations

from threading import Event
from time import sleep

import pytest

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_graph import ResearchGraphScheduler
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphAttemptState,
    ResearchGraphNode,
    ResearchGraphPlan,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)
from noetrium_platform.research.execution.policy.api import AdmissionBudget


class _AdmissionAwareStore(SQLiteResearchGraphExecutionStore):
    def __init__(self, path, pool: ResearchExecutionPool) -> None:
        super().__init__(path)
        self.pool = pool
        self.claim_in_flight: list[int] = []
        self.renewed = Event()

    def claim(self, *args, **kwargs):
        snapshot = self.pool.orchestration_admission_snapshot()
        self.claim_in_flight.append(snapshot.in_flight)
        if snapshot.in_flight <= 0:
            raise AssertionError(
                "durable claim occurred before resource admission"
            )
        return super().claim(*args, **kwargs)

    def renew_leases(self, *args, **kwargs):
        rows = super().renew_leases(*args, **kwargs)
        self.renewed.set()
        return rows


class _Executor:
    def __init__(self, renewed: Event) -> None:
        self.renewed = renewed
        self.calls: list[str] = []

    def execute(self, context, node, *, deadline) -> None:
        del deadline
        self.calls.append(node.node_id)
        context.checkpoint()
        if node.node_id == "a":
            if not self.renewed.wait(2.0):
                raise TimeoutError(
                    "scheduler did not renew active lease while capacity was full"
                )
        context.checkpoint()


def _pool() -> ResearchExecutionPool:
    concurrency = ConcurrencyBudget(
        max_blocking_io_workers=1,
        max_blocking_io_in_flight=1,
        max_async_io_in_flight=1,
        max_cpu_workers=1,
        max_cpu_in_flight=1,
        max_serial_workers=1,
    )
    admission = AdmissionBudget(
        max_total_in_flight=1,
        max_in_flight_per_group=1,
        max_in_flight_per_tenant=1,
        max_in_flight_per_resource=1,
        max_blocking_io_in_flight=1,
        max_async_io_in_flight=1,
        max_cpu_in_flight=1,
        max_serial_in_flight=1,
    )
    return ResearchExecutionPool(
        orchestration_concurrency_budget=concurrency,
        orchestration_admission_budget=admission,
    )


def _plan() -> ResearchGraphPlan:
    return ResearchGraphPlan(
        "admission-before-claim",
        canonical_digest({"revision": "admission-before-claim"}),
        (
            ResearchGraphNode(
                "a",
                canonical_digest({"node": "a"}),
            ),
            ResearchGraphNode(
                "b",
                canonical_digest({"node": "b"}),
            ),
        ),
    )


def test_resource_admission_precedes_claim_and_does_not_starve_lease_renewal(
    tmp_path,
) -> None:
    pool = _pool()
    store = _AdmissionAwareStore(tmp_path / "graph.sqlite3", pool)
    executor = _Executor(store.renewed)
    scheduler = ResearchGraphScheduler(
        _plan(),
        executor,
        execution_pool=pool,
        execution_store=store,
        execution_id="execution-admission-before-claim",
        lease_seconds=0.12,
    )
    try:
        report = scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert report.failed_node_ids == ()
    assert report.blocked_node_ids == ()
    assert report.succeeded_node_ids == ("a", "b")
    assert executor.calls == ["a", "b"]
    assert store.renewed.is_set()
    assert store.claim_in_flight == [1, 1]
    assert len(store.attempts("execution-admission-before-claim", "a")) == 1
    assert len(store.attempts("execution-admission-before-claim", "b")) == 1


class _FailRenewStore(SQLiteResearchGraphExecutionStore):
    def __init__(self, path) -> None:
        super().__init__(path)
        self.renew_attempted = Event()

    def renew_leases(self, *args, **kwargs):
        self.renew_attempted.set()
        raise OSError("simulated durable lease renewal failure")


class _CancellationAwareExecutor:
    def __init__(self) -> None:
        self.started = Event()
        self.cancelled = Event()

    def execute(self, context, node, *, deadline) -> None:
        del node, deadline
        self.started.set()
        while True:
            try:
                context.checkpoint()
            except BaseException:
                self.cancelled.set()
                raise
            sleep(0.005)


def test_durable_lease_heartbeat_failure_cancels_running_workload(
    tmp_path,
) -> None:
    pool = _pool()
    plan = ResearchGraphPlan(
        "heartbeat-owner-loss",
        canonical_digest({"revision": "heartbeat-owner-loss"}),
        (
            ResearchGraphNode(
                "node",
                canonical_digest({"node": "node"}),
            ),
        ),
    )
    store = _FailRenewStore(tmp_path / "heartbeat-owner-loss.sqlite3")
    executor = _CancellationAwareExecutor()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        execution_store=store,
        execution_id="execution-heartbeat-owner-loss",
        lease_seconds=0.12,
    )
    try:
        with pytest.raises(BaseException):
            scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    # Renewal authority can fail in the narrow CLAIMED -> RUNNING boundary.
    # Both outcomes are safe: either the user executor is fenced before it
    # starts, or a started executor observes cancellation. Requiring STARTED
    # unconditionally makes the safety test scheduler-timing dependent.
    assert store.renew_attempted.is_set()
    assert (not executor.started.is_set()) or executor.cancelled.is_set()


class _FailOnceStartStore(SQLiteResearchGraphExecutionStore):
    def __init__(self, path) -> None:
        super().__init__(path)
        self.failed = False

    def mark_running(self, *args, **kwargs):
        if not self.failed:
            self.failed = True
            raise OSError("simulated durable start transition failure")
        return super().mark_running(*args, **kwargs)


class _ImmediateExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, context, node, *, deadline) -> None:
        del deadline
        context.checkpoint()
        self.calls.append(node.node_id)
        context.checkpoint()


def test_claim_committed_before_start_failure_is_abandoned_and_retried_exactly(
    tmp_path,
) -> None:
    pool = _pool()
    plan = ResearchGraphPlan(
        "claim-start-recovery",
        canonical_digest({"revision": "claim-start-recovery"}),
        (
            ResearchGraphNode(
                "node",
                canonical_digest({"node": "node"}),
            ),
        ),
    )
    store = _FailOnceStartStore(tmp_path / "claim-start.sqlite3")
    executor = _ImmediateExecutor()
    scheduler = ResearchGraphScheduler(
        plan,
        executor,
        execution_pool=pool,
        execution_store=store,
        execution_id="execution-claim-start-recovery",
        lease_seconds=0.12,
    )
    try:
        report = scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert report.succeeded_node_ids == ("node",)
    assert report.failed_node_ids == ()
    assert executor.calls == ["node"]
    attempts = store.attempts("execution-claim-start-recovery", "node")
    assert len(attempts) >= 2
    assert all(
        attempt.state
        in {
            ResearchGraphAttemptState.ABANDONED_BEFORE_START,
            ResearchGraphAttemptState.EXPIRED_BEFORE_START,
        }
        for attempt in attempts[:-1]
    )
    assert all(attempt.started_at_ns is None for attempt in attempts[:-1])
    assert attempts[-1].state is ResearchGraphAttemptState.SUCCEEDED
    assert attempts[-1].started_at_ns is not None
