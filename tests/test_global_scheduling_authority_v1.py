from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
import time

from noetrium_platform.foundation.kernel.concurrency.api import ExecutionLaneKind
from noetrium_platform.foundation.kernel.concurrency.scheduling.api import (
    ExecutionPriority,
    SchedulingCandidate,
)
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
    UnifiedSchedulingAuthority,
)
from noetrium_platform.research.execution.policy.api import (
    AdmissionBudget,
    AdmissionIdentity,
)
from noetrium_platform.research.execution.policy.runtime import (
    HierarchicalAdmissionAuthority,
)


def _domain(
    scheduling_authority: UnifiedSchedulingAuthority,
) -> HierarchicalAdmissionAuthority:
    return HierarchicalAdmissionAuthority(
        budget=AdmissionBudget(max_total_in_flight=1),
        scheduling_authority=scheduling_authority,
    )


def _register(
    authority: HierarchicalAdmissionAuthority,
    group_id: str,
    tenant_id: str,
) -> None:
    authority.register_group(
        group_id,
        identity=AdmissionIdentity(tenant_id=tenant_id),
    )


def test_service_consumed_in_one_domain_changes_order_in_another() -> None:
    scheduling = UnifiedSchedulingAuthority()
    left = _domain(scheduling)
    right = _domain(scheduling)

    _register(left, "left-a", "tenant-a")
    _register(right, "blocker", "tenant-blocker")
    _register(right, "right-a", "tenant-a")
    _register(right, "right-b", "tenant-b")

    # Give A measurable service in an independent physical admission domain.
    lease = left.acquire(
        "left-a",
        ExecutionLaneKind.BLOCKING_IO,
        deadline=None,
        cancellation=None,
    )
    time.sleep(0.01)
    lease.release()

    blocker = right.acquire(
        "blocker",
        ExecutionLaneKind.BLOCKING_IO,
        deadline=None,
        cancellation=None,
    )
    granted: list[str] = []

    def acquire(group_id: str, tenant: str) -> None:
        lease = right.acquire(
            group_id,
            ExecutionLaneKind.BLOCKING_IO,
            deadline=None,
            cancellation=None,
        )
        granted.append(tenant)
        lease.release()

    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(acquire, "right-a", "tenant-a")
        b = executor.submit(acquire, "right-b", "tenant-b")

        wait_deadline = time.monotonic() + 2.0
        while right.snapshot().waiting != 2:
            if time.monotonic() >= wait_deadline:
                raise AssertionError("both cross-domain contenders did not queue")
            time.sleep(0.001)

        blocker.release()
        a.result(timeout=2)
        b.result(timeout=2)

    assert granted == ["tenant-b", "tenant-a"]
    assert right.snapshot().in_flight == 0
    assert right.snapshot().waiting == 0

    left.close()
    right.close()


def test_equal_relative_deadlines_do_not_collapse_vtc_fairness_to_fifo() -> None:
    scheduling = UnifiedSchedulingAuthority()
    scheduling.record_grant(
        tenant_id="tenant-a",
        flow_id="flow-a0",
        reserved_service_quanta=10,
    )
    scheduling.record_completion(
        tenant_id="tenant-a",
        flow_id="flow-a0",
        service_quanta=10,
        reserved_service_quanta=10,
    )
    now = 100.0
    earlier_a = SchedulingCandidate(
        ticket=1,
        group_id="flow-a1",
        priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=90.0,
        tenant_id="tenant-a",
        flow_id="flow-a1",
        deadline_monotonic=105.000,
        estimated_service_seconds=0.1,
    )
    later_b = SchedulingCandidate(
        ticket=2,
        group_id="flow-b1",
        priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=90.001,
        tenant_id="tenant-b",
        flow_id="flow-b1",
        deadline_monotonic=105.001,
        estimated_service_seconds=0.1,
    )
    assert scheduling.select(
        (earlier_a, later_b),
        now_monotonic=now,
    ) == 2


def test_deadline_latest_start_boundary_preempts_fair_share_when_infeasible() -> None:
    scheduling = UnifiedSchedulingAuthority()
    # B has already consumed service and would normally lose to A on VTC.
    scheduling.record_grant(
        tenant_id="tenant-b",
        flow_id="flow-b0",
        reserved_service_quanta=10,
    )
    scheduling.record_completion(
        tenant_id="tenant-b",
        flow_id="flow-b0",
        service_quanta=10,
        reserved_service_quanta=10,
    )
    now = 100.0
    fair_a = SchedulingCandidate(
        ticket=1,
        group_id="flow-a1",
        priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=99.0,
        tenant_id="tenant-a",
        flow_id="flow-a1",
        deadline_monotonic=110.0,
        estimated_service_seconds=1.0,
    )
    at_risk_b = SchedulingCandidate(
        ticket=2,
        group_id="flow-b1",
        priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=99.1,
        tenant_id="tenant-b",
        flow_id="flow-b1",
        deadline_monotonic=100.5,
        estimated_service_seconds=0.5,
    )
    assert scheduling.select(
        (fair_a, at_risk_b),
        now_monotonic=now,
    ) == 2

def test_same_tenant_flow_fairness_precedes_static_cost_optimization() -> None:
    scheduling = UnifiedSchedulingAuthority()
    # One cheap flow has already consumed substantial service. A newly ready
    # expensive flow in the same tenant must receive service before the cheap
    # flow can continue; otherwise static cost creates deterministic starvation.
    scheduling.record_grant(
        tenant_id="paper",
        flow_id="cheap-baseline",
        reserved_service_quanta=100,
    )
    scheduling.record_completion(
        tenant_id="paper",
        flow_id="cheap-baseline",
        service_quanta=100,
        reserved_service_quanta=100,
    )
    now = 100.0
    cheap_old = SchedulingCandidate(
        ticket=1,
        group_id="cheap-baseline",
        priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=90.0,
        tenant_id="paper",
        flow_id="cheap-baseline",
        expected_waste_cost=1.0,
        estimated_service_seconds=1.0,
    )
    expensive_new = SchedulingCandidate(
        ticket=2,
        group_id="expensive-demo",
        priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=99.0,
        tenant_id="paper",
        flow_id="expensive-demo",
        expected_waste_cost=1_000_000.0,
        estimated_service_cost=1_000_000.0,
    )

    assert scheduling.select(
        (cheap_old, expensive_new),
        now_monotonic=now,
    ) == 2

def test_same_tenant_resource_fairness_precedes_new_flow_fifo() -> None:
    scheduling = UnifiedSchedulingAuthority()
    scheduling.record_grant(
        tenant_id="paper",
        resource_id="experiment-e1",
        flow_id="e1-old",
        reserved_service_quanta=100,
    )
    scheduling.record_completion(
        tenant_id="paper",
        resource_id="experiment-e1",
        flow_id="e1-old",
        service_quanta=100,
        reserved_service_quanta=100,
    )
    now = 100.0
    e1_new = SchedulingCandidate(
        ticket=1,
        group_id="e1-new",
        priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=90.0,
        tenant_id="paper",
        resource_id="experiment-e1",
        flow_id="e1-new",
    )
    e2_new = SchedulingCandidate(
        ticket=2,
        group_id="e2-new",
        priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=99.0,
        tenant_id="paper",
        resource_id="experiment-e2",
        flow_id="e2-new",
    )

    assert scheduling.select(
        (e1_new, e2_new),
        now_monotonic=now,
    ) == 2


def test_admission_projects_resource_identity_into_global_scheduling() -> None:
    scheduling = UnifiedSchedulingAuthority()
    authority = _domain(scheduling)
    authority.register_group(
        "served-a",
        identity=AdmissionIdentity(
            tenant_id="paper",
            resource_id="experiment-e1",
        ),
    )
    authority.register_group(
        "new-a",
        identity=AdmissionIdentity(
            tenant_id="paper",
            resource_id="experiment-e1",
        ),
    )
    authority.register_group(
        "new-b",
        identity=AdmissionIdentity(
            tenant_id="paper",
            resource_id="experiment-e2",
        ),
    )

    lease = authority.acquire(
        "served-a",
        ExecutionLaneKind.BLOCKING_IO,
        deadline=None,
        cancellation=None,
    )
    lease.release()

    blocker = authority.acquire(
        "served-a",
        ExecutionLaneKind.BLOCKING_IO,
        deadline=None,
        cancellation=None,
    )
    granted: list[str] = []

    def acquire(group_id: str) -> None:
        lease = authority.acquire(
            group_id,
            ExecutionLaneKind.BLOCKING_IO,
            deadline=None,
            cancellation=None,
        )
        granted.append(group_id)
        lease.release()

    with ThreadPoolExecutor(max_workers=2) as executor:
        left = executor.submit(acquire, "new-a")
        right = executor.submit(acquire, "new-b")
        wait_deadline = time.monotonic() + 2.0
        while authority.snapshot().waiting != 2:
            if time.monotonic() >= wait_deadline:
                raise AssertionError("resource contenders did not queue")
            time.sleep(0.001)
        blocker.release()
        left.result(timeout=2)
        right.result(timeout=2)

    assert granted == ["new-b", "new-a"]
    authority.close()

def test_fair_service_debt_precedes_returning_flow_continuity() -> None:
    scheduling = UnifiedSchedulingAuthority()
    scheduling.record_grant(
        tenant_id="paper",
        resource_id="experiment",
        flow_id="returning",
    )
    scheduling.record_completion(
        tenant_id="paper",
        resource_id="experiment",
        flow_id="returning",
        service_quanta=1_000_000_000,
    )
    returning = SchedulingCandidate(
        ticket=1,
        group_id="returning",
        priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=1.0,
        tenant_id="paper",
        resource_id="experiment",
        flow_id="returning",
        continuity_rank=0,
    )
    unserved = SchedulingCandidate(
        ticket=2,
        group_id="unserved",
        priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=2.0,
        tenant_id="paper",
        resource_id="experiment",
        flow_id="unserved",
        continuity_rank=1,
    )

    assert scheduling.select(
        (returning, unserved),
        now_monotonic=3.0,
    ) == 2


def test_fair_service_debt_precedes_declared_priority() -> None:
    scheduling = UnifiedSchedulingAuthority()
    scheduling.record_grant(
        tenant_id="served",
        flow_id="served-flow",
    )
    scheduling.record_completion(
        tenant_id="served",
        flow_id="served-flow",
        service_quanta=1_000_000_000,
    )
    served_high = SchedulingCandidate(
        ticket=1,
        group_id="served-high",
        priority=ExecutionPriority.HIGH,
        enqueued_monotonic=1.0,
        tenant_id="served",
        flow_id="served-high",
    )
    unserved_normal = SchedulingCandidate(
        ticket=2,
        group_id="unserved-normal",
        priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=2.0,
        tenant_id="unserved",
        flow_id="unserved-normal",
    )

    assert scheduling.select(
        (served_high, unserved_normal),
        now_monotonic=3.0,
    ) == 2

def test_rejoining_flow_counter_is_lifted_to_active_sibling_floor() -> None:
    scheduling = UnifiedSchedulingAuthority()
    for flow_id, service in (("returning", 10), ("sibling", 100)):
        scheduling.record_grant(
            tenant_id="paper",
            resource_id="experiment",
            flow_id=flow_id,
        )
        scheduling.record_completion(
            tenant_id="paper",
            resource_id="experiment",
            flow_id=flow_id,
            service_quanta=service,
        )
    scheduling.release_flow("returning", tenant_id="paper", resource_id="experiment")

    # Keep sibling backlogged while returning re-enters. Its old 10-quanta
    # counter must be lifted to at least the sibling's 100-quanta counter.
    scheduling.record_grant(
        tenant_id="paper",
        resource_id="experiment",
        flow_id="sibling",
    )
    scheduling.record_grant(
        tenant_id="paper",
        resource_id="experiment",
        flow_id="returning",
    )
    scheduling.record_completion(
        tenant_id="paper",
        resource_id="experiment",
        flow_id="returning",
        service_quanta=1,
    )
    scheduling.release_flow("returning", tenant_id="paper", resource_id="experiment")
    scheduling.record_completion(
        tenant_id="paper",
        resource_id="experiment",
        flow_id="sibling",
        service_quanta=1,
    )

    returning = SchedulingCandidate(
        ticket=1,
        group_id="returning",
        priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=1.0,
        tenant_id="paper",
        resource_id="experiment",
        flow_id="returning",
    )
    sibling = SchedulingCandidate(
        ticket=2,
        group_id="sibling",
        priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=2.0,
        tenant_id="paper",
        resource_id="experiment",
        flow_id="sibling",
    )
    assert scheduling.select(
        (returning, sibling),
        now_monotonic=3.0,
    ) == 2


def test_idle_rejoin_inherits_last_departing_sibling_counter() -> None:
    scheduling = UnifiedSchedulingAuthority()
    scheduling.record_grant(
        tenant_id="paper",
        resource_id="experiment",
        flow_id="old",
    )
    scheduling.record_completion(
        tenant_id="paper",
        resource_id="experiment",
        flow_id="old",
        service_quanta=50,
    )
    scheduling.release_flow("old", tenant_id="paper", resource_id="experiment")

    scheduling.record_grant(
        tenant_id="paper",
        resource_id="experiment",
        flow_id="new",
    )
    new_state = scheduling._flow_states[scheduling._flow_key("paper", "experiment", "new")]
    with new_state.lock:
        assert new_state.service_quanta == 50
    scheduling.record_completion(
        tenant_id="paper",
        resource_id="experiment",
        flow_id="new",
        service_quanta=1,
    )


def test_reused_local_flow_id_has_distinct_parent_qualified_identities() -> None:
    scheduling = UnifiedSchedulingAuthority()
    scheduling.record_grant(
        tenant_id="paper-a", resource_id="experiment-a", flow_id="same-flow",
    )
    scheduling.record_completion(
        tenant_id="paper-a", resource_id="experiment-a",
        flow_id="same-flow", service_quanta=1,
    )
    scheduling.release_flow(
        "same-flow", tenant_id="paper-a", resource_id="experiment-a",
    )
    scheduling.record_grant(
        tenant_id="paper-b", resource_id="experiment-b", flow_id="same-flow",
    )
    first_key = scheduling._flow_key("paper-a", "experiment-a", "same-flow")
    second_key = scheduling._flow_key("paper-b", "experiment-b", "same-flow")
    assert first_key != second_key
    assert scheduling._flow_states[first_key].retire_requested
    assert not scheduling._flow_states[second_key].retire_requested
    scheduling.record_completion(
        tenant_id="paper-b", resource_id="experiment-b",
        flow_id="same-flow", service_quanta=3,
    )
    assert scheduling._flow_states[first_key].service_quanta == 1
    assert scheduling._flow_states[second_key].service_quanta == 3

def test_counter_lift_applies_at_tenant_and_resource_levels() -> None:
    scheduling = UnifiedSchedulingAuthority()
    scheduling.record_grant(
        tenant_id="paper-a",
        resource_id="experiment-a",
        flow_id="a-old",
    )
    scheduling.record_completion(
        tenant_id="paper-a",
        resource_id="experiment-a",
        flow_id="a-old",
        service_quanta=10,
    )
    scheduling.record_grant(
        tenant_id="paper-b",
        resource_id="experiment-b",
        flow_id="b-old",
    )
    scheduling.record_completion(
        tenant_id="paper-b",
        resource_id="experiment-b",
        flow_id="b-old",
        service_quanta=100,
    )

    # B is backlogged; reactivating A must lift the tenant counter.
    scheduling.record_grant(
        tenant_id="paper-b",
        resource_id="experiment-b",
        flow_id="b-live",
    )
    scheduling.record_grant(
        tenant_id="paper-a",
        resource_id="experiment-a",
        flow_id="a-live",
    )
    tenant_a = scheduling._tenant_states["paper-a"]
    with tenant_a.lock:
        assert tenant_a.service_quanta >= 100

    scheduling.record_completion(
        tenant_id="paper-a",
        resource_id="experiment-a",
        flow_id="a-live",
        service_quanta=1,
    )
    scheduling.record_completion(
        tenant_id="paper-b",
        resource_id="experiment-b",
        flow_id="b-live",
        service_quanta=1,
    )

    # Two resource siblings inside one tenant get the same no-credit rule.
    scheduling.record_grant(
        tenant_id="paper-a",
        resource_id="experiment-c",
        flow_id="c-old",
    )
    scheduling.record_completion(
        tenant_id="paper-a",
        resource_id="experiment-c",
        flow_id="c-old",
        service_quanta=200,
    )
    scheduling.record_grant(
        tenant_id="paper-a",
        resource_id="experiment-c",
        flow_id="c-live",
    )
    scheduling.record_grant(
        tenant_id="paper-a",
        resource_id="experiment-a",
        flow_id="a-return",
    )
    key = scheduling._resource_key("paper-a", "experiment-a")
    assert key is not None
    resource_a = scheduling._resource_states[key]
    with resource_a.lock:
        # experiment-a had 11 service before this rejoin; C has at least 200.
        assert resource_a.service_quanta >= 200

def test_provisional_grant_rollback_does_not_create_service_debt() -> None:
    scheduling = UnifiedSchedulingAuthority()
    scheduling.record_grant(
        tenant_id="paper",
        resource_id="experiment",
        flow_id="flow",
    )
    scheduling.rollback_grant(
        tenant_id="paper",
        resource_id="experiment",
        flow_id="flow",
    )

    flow = scheduling._flow_states[scheduling._flow_key("paper", "experiment", "flow")]
    resource_key = scheduling._resource_key("paper", "experiment")
    assert resource_key is not None
    resource = scheduling._resource_states[resource_key]
    tenant = scheduling._tenant_states["paper"]
    for state in (flow, resource, tenant):
        with state.lock:
            assert state.in_flight == 0
            assert state.service_quanta == 0
            assert state.reserved_service_quanta == 0


def test_sibling_frontier_oracle() -> None:
    scheduler = UnifiedSchedulingAuthority()
    for index in range(120):
        flow = f"oracle-{index}"
        scheduler.record_grant(tenant_id="paper", flow_id=flow)
        if index % 3:
            scheduler.record_completion(tenant_id="paper", flow_id=flow, service_quanta=index + 1)
        for target in tuple(scheduler._flow_states.values())[-3:]:
            siblings = [state for state in scheduler._flow_states.values() if state is not target and state.parent == target.parent]
            active = [state.service_quanta + state.reserved_service_quanta for state in siblings if state.in_flight]
            latest = [(state.last_completion, state.service_quanta + state.reserved_service_quanta) for state in siblings if state.last_completion >= 0]
            expected = min(active) if active else max(latest)[1] if latest else 0
            assert target.frontier.floor(exclude=target) == expected


def test_scheduler_hash_trie_collision_and_snapshot() -> None:
    from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime.unified import (
        _PersistentStateIndex, _SchedulingEntityState,
    )

    class CollidingIndex(_PersistentStateIndex):
        @staticmethod
        def _hash(key: str) -> int:
            return 0

    index = CollidingIndex()
    for index_number in range(60):
        index.publish(f"same-hash-{index_number}", _SchedulingEntityState(parent=()))
    snapshot = index._root
    index.publish("next", _SchedulingEntityState(parent=()))
    assert len(index) == 61
    assert len(tuple(index)) == 61
    for index_number in range(60):
        assert index[f"same-hash-{index_number}"].parent == ()
    assert snapshot is not index._root
    assert index.get("missing") is None


def test_parallel_scheduler_registry_publication() -> None:
    scheduling = UnifiedSchedulingAuthority()

    def apply(index: int) -> None:
        for step in range(120):
            flow = f"parallel-{index}-{step}"
            scheduling.record_grant(tenant_id=f"tenant-{index}", flow_id=flow)
            scheduling.record_completion(
                tenant_id=f"tenant-{index}", flow_id=flow, service_quanta=step + 1,
            )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(apply, range(8)))
    assert len(scheduling._flow_states) == 960
    assert len(scheduling._tenant_states) == 8


def test_admission_cancellation_without_deadline_wakes() -> None:
    import pytest
    from noetrium_platform.foundation.kernel.concurrency.api import TaskCancelled
    from noetrium_platform.foundation.kernel.concurrency.runtime.cancellation import _CancellationState

    scheduling = UnifiedSchedulingAuthority()
    authority = _domain(scheduling)
    _register(authority, "holder", "tenant-holder")
    _register(authority, "cancelled", "tenant-cancelled")
    held = authority.acquire(
        "holder", ExecutionLaneKind.BLOCKING_IO,
        deadline=None, cancellation=None,
    )
    cancel = _CancellationState()
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(
            authority.acquire, "cancelled", ExecutionLaneKind.BLOCKING_IO,
            deadline=None, cancellation=cancel,
        )
        latest = time.monotonic() + 3
        while authority.snapshot().waiting != 1:
            if time.monotonic() >= latest:
                raise AssertionError("admission waiter was not queued")
            time.sleep(0.001)
        cancel.cancel("stop queued admission")
        with pytest.raises(TaskCancelled, match="stop queued admission"):
            pending.result(timeout=2)
    held.release()
    assert authority.snapshot().waiting == 0
    authority.close()


def test_hierarchical_completion_rejects_drift_atomically() -> None:
    import pytest
    scheduling = UnifiedSchedulingAuthority()
    scheduling.record_grant(
        tenant_id="paper", resource_id="experiment", flow_id="flow",
        reserved_service_quanta=7,
    )
    flow = scheduling._flow_states[scheduling._flow_key("paper", "experiment", "flow")]
    resource = scheduling._resource_states[scheduling._resource_key("paper", "experiment")]
    tenant = scheduling._tenant_states["paper"]
    # Emulate a corrupted parent: the lower level is still valid. A failed
    # completion must not retire the flow while leaving its parent live.
    with resource.lock:
        resource.reserved_service_quanta = 0
    prior = [(state.in_flight, state.reserved_service_quanta, state.service_quanta)
             for state in (flow, resource, tenant)]
    with pytest.raises(RuntimeError, match="resource service reservation underflow"):
        scheduling.record_completion(
            tenant_id="paper", resource_id="experiment", flow_id="flow",
            service_quanta=5, reserved_service_quanta=7,
        )
    assert prior == [(state.in_flight, state.reserved_service_quanta, state.service_quanta)
                     for state in (flow, resource, tenant)]
    with pytest.raises(RuntimeError, match="resource rollback service reservation underflow"):
        scheduling.rollback_grant(
            tenant_id="paper", resource_id="experiment", flow_id="flow",
            reserved_service_quanta=7,
        )
    assert prior == [(state.in_flight, state.reserved_service_quanta, state.service_quanta)
                     for state in (flow, resource, tenant)]


def test_admission_projection_unchanged_on_scheduling_failure() -> None:
    import pytest

    class FailingAuthority(UnifiedSchedulingAuthority):
        failing: str | None = None

        def record_grant(self, **kwargs):
            if self.failing == "grant":
                raise RuntimeError("injected scheduling grant failure")
            return super().record_grant(**kwargs)

        def rollback_grant(self, **kwargs):
            if self.failing == "rollback":
                raise RuntimeError("injected scheduling rollback failure")
            return super().rollback_grant(**kwargs)

        def record_completion(self, **kwargs):
            if self.failing == "completion":
                raise RuntimeError("injected scheduling completion failure")
            return super().record_completion(**kwargs)

    scheduling = FailingAuthority()
    admission = _domain(scheduling)
    _register(admission, "group", "paper")
    scheduling.failing = "grant"
    with pytest.raises(RuntimeError, match="injected scheduling grant"):
        admission.acquire(
            "group", ExecutionLaneKind.BLOCKING_IO, deadline=None, cancellation=None
        )
    assert admission.snapshot().in_flight == 0

    scheduling.failing = None
    lease = admission.acquire(
        "group", ExecutionLaneKind.BLOCKING_IO, deadline=None, cancellation=None
    )
    scheduling.failing = "rollback"
    with pytest.raises(RuntimeError, match="injected scheduling rollback"):
        lease.rollback()
    assert admission.snapshot().in_flight == 1
    scheduling.failing = "completion"
    with pytest.raises(RuntimeError, match="injected scheduling completion"):
        lease.release()
    assert admission.snapshot().in_flight == 1
    scheduling.failing = None
    lease.release()
    assert admission.snapshot().in_flight == 0
    admission.close()


def test_immediate_grant_provisional_capacity_is_hidden_but_not_overbooked() -> None:
    class BlockingGrant(UnifiedSchedulingAuthority):
        def __init__(self) -> None:
            super().__init__()
            self.entered = Event()
            self.proceed = Event()

        def record_grant(self, **kwargs):
            self.entered.set()
            assert self.proceed.wait(2.0)
            return super().record_grant(**kwargs)

    scheduling = BlockingGrant()
    admission = HierarchicalAdmissionAuthority(
        budget=AdmissionBudget(max_total_in_flight=1),
        scheduling_authority=scheduling,
    )
    _register(admission, "first", "paper")
    _register(admission, "second", "paper")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            admission.try_acquire,
            "first",
            ExecutionLaneKind.ASYNC_IO,
            deadline=None,
            cancellation=None,
        )
        assert scheduling.entered.wait(1.0)
        # The scheduler has not durably granted yet, so public admission truth
        # stays unchanged even though feasibility is privately reserved.
        assert admission.snapshot().in_flight == 0
        assert admission.try_acquire(
            "second",
            ExecutionLaneKind.ASYNC_IO,
            deadline=None,
            cancellation=None,
        ) is None
        try:
            admission.unregister_group("first")
        except RuntimeError as exc:
            assert "active permits" in str(exc)
        else:
            raise AssertionError("provisional grant allowed group retirement")
        scheduling.proceed.set()
        lease = future.result(timeout=2.0)
    assert lease is not None
    assert admission.snapshot().in_flight == 1
    lease.release()
    assert admission.snapshot().in_flight == 0
    admission.close()


def test_close_waits_for_preexisting_provisional_grant_without_polling() -> None:
    class BlockingGrant(UnifiedSchedulingAuthority):
        def __init__(self) -> None:
            super().__init__()
            self.entered = Event()
            self.proceed = Event()

        def record_grant(self, **kwargs):
            self.entered.set()
            assert self.proceed.wait(2.0)
            return super().record_grant(**kwargs)

    scheduling = BlockingGrant()
    admission = _domain(scheduling)
    _register(admission, "group", "paper")
    with ThreadPoolExecutor(max_workers=1) as pool:
        granted = pool.submit(
            admission.try_acquire,
            "group",
            ExecutionLaneKind.ASYNC_IO,
            deadline=None,
            cancellation=None,
        )
        assert scheduling.entered.wait(1.0)
        closed = Event()
        closer = Thread(target=lambda: (admission.close(), closed.set()))
        closer.start()
        time.sleep(0.02)
        assert not closed.is_set()
        scheduling.proceed.set()
        lease = granted.result(timeout=2.0)
        assert lease is not None
        assert closed.wait(1.0)
        closer.join(timeout=1.0)
    assert admission.snapshot().closed
    assert admission.snapshot().in_flight == 1
    lease.release()
    assert admission.snapshot().in_flight == 0


def test_completion_settlement_releases_admission_lock_but_keeps_capacity_owned() -> None:
    class BlockingCompletion(UnifiedSchedulingAuthority):
        def __init__(self) -> None:
            super().__init__()
            self.entered = Event()
            self.proceed = Event()

        def record_completion(self, **kwargs):
            self.entered.set()
            assert self.proceed.wait(2.0)
            return super().record_completion(**kwargs)

    scheduling = BlockingCompletion()
    admission = HierarchicalAdmissionAuthority(
        budget=AdmissionBudget(max_total_in_flight=1),
        scheduling_authority=scheduling,
    )
    _register(admission, "first", "paper")
    _register(admission, "second", "paper")
    lease = admission.acquire(
        "first", ExecutionLaneKind.ASYNC_IO, deadline=None, cancellation=None
    )
    released = Event()
    # Seed one already-active settlement caller so the public lease.release()
    # deterministically takes the concurrent-settlement branch under test.
    admission._enter_settlement_call()
    try:
        thread = Thread(target=lambda: (lease.release(), released.set()))
        thread.start()
        assert scheduling.entered.wait(1.0)
        # Snapshot and other admission probes must not convoy behind durable
        # service settlement, while capacity remains conservatively occupied.
        assert admission.snapshot().in_flight == 1
        assert admission.try_acquire(
            "second", ExecutionLaneKind.ASYNC_IO, deadline=None, cancellation=None
        ) is None
        scheduling.proceed.set()
        assert released.wait(1.0)
        thread.join(timeout=1.0)
    finally:
        admission._leave_settlement_call()
    assert admission.snapshot().in_flight == 0
    admission.close()


def test_expired_deadline_does_not_preempt_live_feasible_work() -> None:
    scheduling = UnifiedSchedulingAuthority()
    expired = SchedulingCandidate(
        ticket=1, group_id="expired", priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=1.0, tenant_id="overdue",
        deadline_monotonic=9.0, estimated_service_seconds=1.0,
    )
    feasible = SchedulingCandidate(
        ticket=2, group_id="feasible", priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=2.0, tenant_id="live",
        deadline_monotonic=20.0, estimated_service_seconds=1.0,
    )
    assert scheduling.select((expired, feasible), now_monotonic=10.0) == 2


def test_negative_estimated_laxity_does_not_outweigh_fair_service_debt() -> None:
    scheduling = UnifiedSchedulingAuthority()
    consumed = SchedulingCandidate(
        ticket=1, group_id="consumed", priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=1.0, tenant_id="heavy",
        deadline_monotonic=10.1, estimated_service_seconds=10.0,
    )
    fresh = SchedulingCandidate(
        ticket=2, group_id="fresh", priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=2.0, tenant_id="fresh",
        deadline_monotonic=10.2, estimated_service_seconds=1.0,
    )
    scheduling.record_grant(tenant_id="heavy", flow_id="served")
    scheduling.record_completion(tenant_id="heavy", flow_id="served", service_quanta=100)
    # Both future deadlines are urgent; the more negative uncertain estimate
    # must not beat the tenant that has consumed no service.
    assert scheduling.select((consumed, fresh), now_monotonic=10.0) == 2


def test_resource_identity_is_injective_for_arbitrary_scope_delimiters() -> None:
    scheduler = UnifiedSchedulingAuthority()
    left = scheduler._resource_key("paper::resource::part", "world")
    right = scheduler._resource_key("paper", "part::resource::world")
    assert left != right
    assert scheduler._flow_key(
        "ab", "c", "d",
    ) != scheduler._flow_key(
        "a", "bc", "d",
    )
    for tenant, resource in (
        ("paper::resource::part", "world"),
        ("paper", "part::resource::world"),
    ):
        scheduler.record_grant(
            tenant_id=tenant, resource_id=resource, flow_id="same",
        )
        scheduler.record_completion(
            tenant_id=tenant, resource_id=resource,
            flow_id="same", service_quanta=2,
        )
    assert len(scheduler._resource_states) == 2
    assert len(scheduler._flow_states) == 2


def test_batch_ranking_snapshots_shared_hierarchy_once_and_matches_single_keys() -> None:
    class CountingSchedulingAuthority(UnifiedSchedulingAuthority):
        def __init__(self) -> None:
            super().__init__()
            self.snapshot_calls = 0

        def _state_snapshot(self, state):
            self.snapshot_calls += 1
            return UnifiedSchedulingAuthority._state_snapshot(state)

    scheduling = CountingSchedulingAuthority()
    scheduling.record_grant(
        tenant_id="paper",
        resource_id="gpu",
        flow_id="warm",
        reserved_service_quanta=7,
    )
    scheduling.record_completion(
        tenant_id="paper",
        resource_id="gpu",
        flow_id="warm",
        service_quanta=7,
        reserved_service_quanta=7,
    )
    candidates = tuple(
        SchedulingCandidate(
            ticket=index,
            group_id=f"group-{index}",
            priority=(ExecutionPriority.HIGH if index % 3 == 0 else ExecutionPriority.NORMAL),
            enqueued_monotonic=10.0 + index / 1000.0,
            tenant_id="paper",
            resource_id="gpu",
            flow_id=f"flow-{index}",
            deadline_monotonic=(30.0 + index / 100.0 if index % 4 == 0 else None),
            estimated_service_seconds=(0.25 if index % 4 == 0 else None),
            estimated_service_cost=float(index % 5),
        )
        for index in range(64)
    )

    batch = scheduling.ordering_keys(candidates, now_monotonic=20.0)
    # One tenant snapshot + one resource snapshot + one snapshot for each
    # distinct flow. Shared hierarchy must not be re-locked per candidate.
    assert scheduling.snapshot_calls == len(candidates) + 2

    scheduling.snapshot_calls = 0
    singles = tuple(
        scheduling.ordering_key(candidate, now_monotonic=20.0)
        for candidate in candidates
    )
    assert batch == singles
    assert scheduling.snapshot_calls == len(candidates) * 3
