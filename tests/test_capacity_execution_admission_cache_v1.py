from threading import Thread
import time

from noetrium_platform.research.execution.policy.api import (
    AdmissionBudget,
    AdmissionIdentity,
    AdmissionIntent,
    ExecutionPriority,
)
from noetrium_platform.research.execution.policy.runtime import HierarchicalAdmissionAuthority
from noetrium_platform.foundation.kernel.concurrency.scheduling.api import SchedulingCandidate
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import UnifiedSchedulingAuthority
from noetrium_platform.foundation.kernel.concurrency.api import Deadline, ExecutionLaneKind


class _CountingAdmissionAuthority(HierarchicalAdmissionAuthority):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.can_admit_calls = 0

    def _can_admit(self, group_id, lane_kind, permit_count=1):
        self.can_admit_calls += 1
        return super()._can_admit(group_id, lane_kind, permit_count)


def test_selection_cache_avoids_repeated_full_scan_inside_poll_bucket():
    authority = _CountingAdmissionAuthority(
        budget=AdmissionBudget(max_total_in_flight=32, max_in_flight_per_group=1),
        scheduling_authority=UnifiedSchedulingAuthority(),
    )
    authority.register_group("group", identity=AdmissionIdentity())
    blocker = authority.acquire("group", ExecutionLaneKind.BLOCKING_IO, deadline=None, cancellation=None)
    errors: list[BaseException] = []

    def wait_once() -> None:
        try:
            lease = authority.acquire(
                "group", ExecutionLaneKind.BLOCKING_IO,
                deadline=Deadline.after(2.0), cancellation=None,
            )
            lease.release()
        except BaseException as exc:
            errors.append(exc)

    threads = [Thread(target=wait_once) for _ in range(20)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and authority.snapshot().waiting != len(threads):
        time.sleep(0.002)
    assert authority.snapshot().waiting == len(threads)

    with authority._condition:
        authority.can_admit_calls = 0
        for _ in range(100):
            authority._selected_waiter()
        assert authority.can_admit_calls <= len(threads) * 2

        # The only live shape is capacity-blocked by the group holder. Once
        # parked, unrelated ordering refreshes must not manufacture stale heap
        # rows for it.
        waiter = next(iter(authority._waiters.values()))
        assert authority._shape(waiter) in authority._capacity_block_key_by_shape
        for _ in range(1000):
            authority._push_waiter_order(waiter, time.monotonic())
        assert authority._selection_heap_size() == 0
        authority._selected_waiter()
        assert authority._selection_heap_size() == 0

    blocker.release()
    for thread in threads:
        thread.join(2.0)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert authority.snapshot().waiting == 0
    assert authority.snapshot().in_flight == 0
    authority.close()


def test_saturated_lane_is_skipped_without_scanning_its_waiters():
    from noetrium_platform.research.execution.policy.runtime.authority import _Waiter

    authority = _CountingAdmissionAuthority(
        budget=AdmissionBudget(
            max_total_in_flight=4096,
            max_in_flight_per_group=1,
            max_in_flight_per_tenant=4096,
            max_in_flight_per_resource=4096,
            max_blocking_io_in_flight=1,
            max_async_io_in_flight=4096,
            max_cpu_in_flight=4096,
            max_serial_in_flight=4096,
            max_waiting=10000,
        ),
        scheduling_authority=UnifiedSchedulingAuthority(),
    )
    authority.register_group("blocking-holder", identity=AdmissionIdentity())
    blocker = authority.try_acquire(
        "blocking-holder",
        ExecutionLaneKind.BLOCKING_IO,
        deadline=None,
        cancellation=None,
    )
    assert blocker is not None

    with authority._condition:
        for index in range(2000):
            group_id = f"blocked-{index}"
            authority.register_group(group_id, identity=AdmissionIdentity())
            waiter = _Waiter(
                authority._next_ticket,
                group_id,
                ExecutionLaneKind.BLOCKING_IO,
                1,
                authority._group_intents[group_id],
                0.0,
            )
            authority._next_ticket += 1
            authority._enqueue_waiter(waiter)
        authority.register_group("runnable", identity=AdmissionIdentity())
        runnable = _Waiter(
            authority._next_ticket,
            "runnable",
            ExecutionLaneKind.ASYNC_IO,
            1,
            authority._group_intents["runnable"],
            0.0,
        )
        authority._next_ticket += 1
        authority._enqueue_waiter(runnable)

        authority.can_admit_calls = 0
        authority._selection_cache_version = -1
        assert authority._selected_waiter() is runnable
        # The entire saturated blocking lane is proven infeasible by one
        # counter comparison; only live lanes need per-shape admission checks.
        assert authority.can_admit_calls <= 4

        for ticket in tuple(authority._waiters):
            authority._remove_waiter(ticket)

    blocker.release()
    authority.close()


def test_release_wakes_only_selected_waiter_not_entire_queue():
    from threading import Event, Lock

    authority = _CountingAdmissionAuthority(
        budget=AdmissionBudget(
            max_total_in_flight=1,
            max_in_flight_per_group=1,
            max_waiting=256,
        ),
        scheduling_authority=UnifiedSchedulingAuthority(),
    )
    authority.register_group("blocker", identity=AdmissionIdentity())
    blocker = authority.acquire(
        "blocker",
        ExecutionLaneKind.BLOCKING_IO,
        deadline=None,
        cancellation=None,
    )

    waiter_count = 64
    acquired = Event()
    release_first = Event()
    completed: list[int] = []
    completed_lock = Lock()
    errors: list[BaseException] = []

    def wait_once(index: int) -> None:
        group_id = f"waiter-{index}"
        authority.register_group(group_id, identity=AdmissionIdentity())
        try:
            lease = authority.acquire(
                group_id,
                ExecutionLaneKind.BLOCKING_IO,
                deadline=Deadline.after(5.0),
                cancellation=None,
            )
            if not acquired.is_set():
                acquired.set()
                release_first.wait(2.0)
            lease.release()
            with completed_lock:
                completed.append(index)
        except BaseException as exc:
            errors.append(exc)
        finally:
            try:
                authority.unregister_group(group_id)
            except BaseException as exc:
                errors.append(exc)

    threads = [Thread(target=wait_once, args=(index,)) for index in range(waiter_count)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 2.0
    while (
        time.monotonic() < deadline
        and authority.snapshot().waiting != waiter_count
    ):
        time.sleep(0.002)
    assert authority.snapshot().waiting == waiter_count

    authority.can_admit_calls = 0
    blocker.release()
    assert acquired.wait(2.0)
    # Keep the one selected waiter holding the only permit. Targeted signaling
    # should leave the other 63 threads asleep instead of creating a herd that
    # repeatedly re-runs selection under the authority lock.
    time.sleep(0.05)
    assert authority.can_admit_calls <= 12

    release_first.set()
    for thread in threads:
        thread.join(5.0)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert len(completed) == waiter_count
    authority.unregister_group("blocker")
    authority.close()


def test_admission_records_exact_group_and_lane_service_rate(monkeypatch) -> None:
    import noetrium_platform.research.execution.policy.runtime.authority as authority_runtime

    clock = [10.0]
    monkeypatch.setattr(authority_runtime.time, "monotonic", lambda: clock[0])
    runtime = HierarchicalAdmissionAuthority(
        budget=AdmissionBudget(
            max_total_in_flight=4,
            max_blocking_io_in_flight=4,
            max_async_io_in_flight=4,
            max_cpu_in_flight=4,
            max_serial_in_flight=4,
        ),
        scheduling_authority=UnifiedSchedulingAuthority(),
    )
    runtime.register_group(
        "g",
        identity=AdmissionIdentity(tenant_id="t", resource_id="r"),
    )

    first = runtime.acquire(
        "g",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    clock[0] = 12.0
    first.release()

    second = runtime.acquire(
        "g",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    clock[0] = 16.0
    second.release()

    snapshot = runtime.snapshot()
    group = next(row for row in snapshot.groups if row.group_id == "g")
    lane = next(
        row for row in snapshot.lanes
        if row.lane_kind is ExecutionLaneKind.CPU
    )
    assert group.completed_total == 2
    assert group.cumulative_service_seconds == 6.0
    assert group.mean_service_seconds == 3.0
    assert group.service_rate_per_second == 2.0 / 6.0
    assert lane.completed_total == 2
    assert lane.cumulative_service_seconds == 6.0
    assert lane.mean_service_seconds == 3.0
    assert lane.service_rate_per_second == 2.0 / 6.0


def test_capacity_blocked_shapes_are_parked_until_relevant_scope_changes():
    from noetrium_platform.research.execution.policy.runtime.authority import _Waiter

    authority = HierarchicalAdmissionAuthority(
        budget=AdmissionBudget(
            max_total_in_flight=4096,
            max_in_flight_per_group=8,
            max_in_flight_per_tenant=1,
            max_in_flight_per_resource=4096,
            max_blocking_io_in_flight=4096,
            max_async_io_in_flight=4096,
            max_cpu_in_flight=4096,
            max_serial_in_flight=4096,
            max_waiting=10000,
        ),
        scheduling_authority=UnifiedSchedulingAuthority(),
    )
    authority.register_group(
        "tenant-holder",
        identity=AdmissionIdentity(tenant_id="saturated"),
    )
    holder = authority.acquire(
        "tenant-holder",
        ExecutionLaneKind.ASYNC_IO,
        deadline=None,
        cancellation=None,
    )
    enqueued_at = time.monotonic()

    with authority._condition:
        for index in range(512):
            group_id = f"blocked-{index}"
            authority.register_group(
                group_id,
                identity=AdmissionIdentity(tenant_id="saturated"),
                intent=AdmissionIntent(priority=ExecutionPriority.CRITICAL),
            )
            waiter = _Waiter(
                authority._next_ticket,
                group_id,
                ExecutionLaneKind.ASYNC_IO,
                1,
                authority._group_intents[group_id],
                enqueued_at,
            )
            authority._next_ticket += 1
            authority._enqueue_waiter(waiter)

        authority.register_group(
            "runnable",
            identity=AdmissionIdentity(tenant_id="free"),
        )
        runnable = _Waiter(
            authority._next_ticket,
            "runnable",
            ExecutionLaneKind.ASYNC_IO,
            1,
            authority._group_intents["runnable"],
            enqueued_at,
        )
        authority._next_ticket += 1
        authority._enqueue_waiter(runnable)

        calls = 0
        original = authority._capacity_block_key

        def counted(waiter):
            nonlocal calls
            calls += 1
            return original(waiter)

        authority._capacity_block_key = counted
        authority._selection_cache_version = -1
        assert authority._selected_waiter() is runnable
        first_pass_calls = calls
        # Hierarchical fairness already ranks the unserved free tenant ahead of
        # the saturated tenant, so the healthy runnable path must not scan all
        # blocked shapes merely to prove what the ordering already avoids.
        assert first_pass_calls <= 4
        assert len(authority._capacity_block_key_by_shape) == 0

        # Once the runnable head leaves the queue, the only remaining shapes
        # are capacity-blocked. Discover and park them once.
        authority._remove_waiter(runnable.ticket)
        authority._selection_cache_version = -1
        before_parking = calls
        assert authority._selected_waiter() is None
        parked_pass_calls = calls - before_parking
        assert parked_pass_calls >= 512
        assert len(authority._capacity_block_key_by_shape) == 512

        # Unrelated queue invalidation must not rescan all 512 shapes. Their
        # exact tenant-capacity dependency has not changed.
        authority._invalidate_selection()
        before_repeat = calls
        assert authority._selected_waiter() is None
        assert calls - before_repeat <= 4

        for ticket in tuple(authority._waiters):
            authority._remove_waiter(ticket)

    holder.release()
    authority.close()


def test_relevant_capacity_release_reactivates_parked_shape():
    from noetrium_platform.research.execution.policy.runtime.authority import _Waiter

    authority = HierarchicalAdmissionAuthority(
        budget=AdmissionBudget(
            max_total_in_flight=8,
            max_in_flight_per_group=8,
            max_in_flight_per_tenant=1,
            max_in_flight_per_resource=8,
            max_async_io_in_flight=8,
        ),
        scheduling_authority=UnifiedSchedulingAuthority(),
    )
    authority.register_group(
        "holder",
        identity=AdmissionIdentity(tenant_id="tenant"),
    )
    holder = authority.acquire(
        "holder",
        ExecutionLaneKind.ASYNC_IO,
        deadline=None,
        cancellation=None,
    )
    authority.register_group(
        "blocked",
        identity=AdmissionIdentity(tenant_id="tenant"),
    )
    with authority._condition:
        waiter = _Waiter(
            authority._next_ticket,
            "blocked",
            ExecutionLaneKind.ASYNC_IO,
            1,
            authority._group_intents["blocked"],
            0.0,
        )
        authority._next_ticket += 1
        authority._enqueue_waiter(waiter)
        assert authority._selected_waiter() is None
        assert authority._shape(waiter) in authority._capacity_block_key_by_shape

    holder.release()

    with authority._condition:
        authority._selection_cache_version = -1
        assert authority._selected_waiter() is waiter
        authority._remove_waiter(waiter.ticket)
    authority.close()



def test_service_fairness_requires_no_time_based_reindexing(monkeypatch) -> None:
    import noetrium_platform.research.execution.policy.runtime.authority as authority_runtime
    from noetrium_platform.research.execution.policy.runtime.authority import _Waiter

    clock = [100.0]
    monkeypatch.setattr(authority_runtime.time, "monotonic", lambda: clock[0])
    authority = HierarchicalAdmissionAuthority(
        budget=AdmissionBudget(
            max_total_in_flight=4096,
            max_in_flight_per_group=4096,
            max_in_flight_per_tenant=4096,
            max_in_flight_per_resource=4096,
            max_blocking_io_in_flight=4096,
            max_async_io_in_flight=4096,
            max_cpu_in_flight=4096,
            max_serial_in_flight=4096,
            max_waiting=10000,
        ),
        scheduling_authority=UnifiedSchedulingAuthority(),
    )

    with authority._condition:
        for index in range(512):
            group_id = f"fair-{index}"
            authority.register_group(
                group_id,
                identity=AdmissionIdentity(),
                intent=AdmissionIntent(priority=ExecutionPriority.LOW),
            )
            waiter = _Waiter(
                authority._next_ticket,
                group_id,
                ExecutionLaneKind.ASYNC_IO,
                1,
                authority._group_intents[group_id],
                100.0 + index,
            )
            authority._next_ticket += 1
            authority._enqueue_waiter(waiter)

        rebuilds = 0
        original_rebuild = authority._rebuild_selection_heaps

        def counted_rebuild(now):
            nonlocal rebuilds
            rebuilds += 1
            return original_rebuild(now)

        authority._rebuild_selection_heaps = counted_rebuild
        authority._selection_cache_version = -1
        first = authority._selected_waiter()
        initial_rebuilds = rebuilds
        assert first is not None

        # Advancing wall time alone cannot change scheduling order anymore.
        for offset in range(1, 64):
            clock[0] = 100.0 + offset
            assert authority._selected_waiter() is first

        assert rebuilds == initial_rebuilds
        for ticket in tuple(authority._waiters):
            authority._remove_waiter(ticket)
    authority.close()


def test_lower_priority_less_served_flow_precedes_higher_priority_served_flow() -> None:
    scheduling = UnifiedSchedulingAuthority()
    scheduling.record_grant(
        tenant_id="paper",
        flow_id="high-served",
        reserved_service_quanta=100,
    )
    scheduling.record_completion(
        tenant_id="paper",
        flow_id="high-served",
        service_quanta=100,
        reserved_service_quanta=100,
    )
    candidates = (
        SchedulingCandidate(
            1,
            "high-served",
            ExecutionPriority.HIGH,
            10.0,
            tenant_id="paper",
            flow_id="high-served",
        ),
        SchedulingCandidate(
            2,
            "low-unserved",
            ExecutionPriority.LOW,
            11.0,
            tenant_id="paper",
            flow_id="low-unserved",
        ),
    )
    assert scheduling.select(candidates, now_monotonic=12.0) == 2



def test_service_revision_rebuild_batches_scheduling_projection():
    from noetrium_platform.research.execution.policy.runtime.authority import _Waiter

    class _CountingScheduling(UnifiedSchedulingAuthority):
        def __init__(self):
            super().__init__()
            self.single_calls = 0
            self.batch_calls = 0
            self.batch_sizes = []

        def ordering_key(self, candidate, *, now_monotonic):
            self.single_calls += 1
            return super().ordering_key(candidate, now_monotonic=now_monotonic)

        def ordering_keys(self, candidates, *, now_monotonic):
            self.batch_calls += 1
            self.batch_sizes.append(len(candidates))
            return super().ordering_keys(candidates, now_monotonic=now_monotonic)

    scheduling = _CountingScheduling()
    authority = HierarchicalAdmissionAuthority(
        budget=AdmissionBudget(
            max_total_in_flight=256,
            max_in_flight_per_group=4,
            max_in_flight_per_tenant=256,
            max_in_flight_per_resource=256,
            max_async_io_in_flight=256,
            max_waiting=256,
        ),
        scheduling_authority=scheduling,
    )
    with authority._condition:
        for index in range(128):
            group_id = f'batch-{index}'
            authority.register_group(group_id, identity=AdmissionIdentity())
            waiter = _Waiter(
                authority._next_ticket,
                group_id,
                ExecutionLaneKind.ASYNC_IO,
                1,
                authority._group_intents[group_id],
                100.0 + index * 1e-6,
            )
            authority._next_ticket += 1
            authority._enqueue_waiter(waiter)
        authority._selection_cache_version = -1
        assert authority._selected_waiter() is not None

        scheduling.single_calls = 0
        scheduling.batch_calls = 0
        scheduling.batch_sizes.clear()
        scheduling.record_grant(tenant_id=None, flow_id='external')
        scheduling.rollback_grant(tenant_id=None, flow_id='external')

        assert authority._selected_waiter() is not None
        assert scheduling.batch_calls == 1
        assert scheduling.batch_sizes == [128]
        # One head may be checked lazily after heap rebuild; the full 128-shape
        # projection must never cross the authority boundary one row at a time.
        assert scheduling.single_calls <= 4

        for ticket in tuple(authority._waiters):
            authority._remove_waiter(ticket)
    authority.close()
