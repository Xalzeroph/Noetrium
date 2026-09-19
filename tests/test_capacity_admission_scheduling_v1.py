from __future__ import annotations

from threading import Event, Thread
import time

import pytest

from noetrium_platform.research.execution.admission.api import AdmissionBudget, AdmissionMode, AdmissionRejected
from noetrium_platform.research.execution.scheduling.api import ExecutionPriority
from noetrium_platform.composition.concurrency import build_execution_concurrency_runtime
from noetrium_platform.foundation.kernel.concurrency.api import (
    SerialMailboxPolicy,
    ConcurrencyBudget,
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskCancelled,
    TaskContextPort,
    TaskFailurePolicy,
)


def _blocking(group, task_id: str, fn, /, *args, deadline=None, **kwargs):
    return group.submit(
        ExecutionSpec(task_id=task_id, lane_kind=ExecutionLaneKind.BLOCKING_IO),
        fn,
        *args,
        deadline=deadline,
        **kwargs,
    )


def _async_io(group, task_id: str, fn, /, *args, deadline=None, **kwargs):
    return group.submit(
        ExecutionSpec(task_id=task_id, lane_kind=ExecutionLaneKind.ASYNC_IO),
        fn,
        *args,
        deadline=deadline,
        **kwargs,
    )


def _serial(group, lane_id: str, task_id: str, fn, /, *args, deadline=None, capacity=None, **kwargs):
    return group.submit(
        ExecutionSpec(task_id=task_id, lane_kind=ExecutionLaneKind.SERIAL, lane_id=lane_id, capacity=capacity),
        fn, *args, deadline=deadline, **kwargs,
    )

def test_global_backpressure_enforces_runtime_and_group_budgets_atomically() -> None:
    runtime = build_execution_concurrency_runtime(
        concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=4,
            max_blocking_io_in_flight=4,
            max_cpu_workers=1,
            default_queue_capacity=4,
        ),
        admission_budget=AdmissionBudget(
            max_total_in_flight=2,
            max_in_flight_per_group=1,
            max_blocking_io_in_flight=2,
        ),
    )
    group_a = runtime.open_task_group(
        "bp-a",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
        admission_mode=AdmissionMode.REJECT,
    )
    group_b = runtime.open_task_group("bp-b", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    release = Event()
    started_a = Event()
    started_b = Event()

    def hold(context: TaskContextPort, started: Event) -> str:
        started.set()
        release.wait(2)
        context.checkpoint()
        return context.group_id

    first = _blocking(group_a, "a-1", hold, started_a)
    second = _blocking(group_b, "b-1", hold, started_b)
    assert started_a.wait(1) and started_b.wait(1)

    with pytest.raises(AdmissionRejected):
        group_a.submit(
            ExecutionSpec(
                task_id="a-reject",
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
            ),
            lambda context: None,
        )

    snapshot = runtime.admission_snapshot()
    assert snapshot.in_flight == 2
    assert dict((row.group_id, row.in_flight) for row in snapshot.groups) == {"bp-a": 1, "bp-b": 1}

    release.set()
    assert first.result(1) == "bp-a"
    assert second.result(1) == "bp-b"
    group_a.close()
    group_b.close()
    assert runtime.admission_snapshot().in_flight == 0
    runtime.close()


def test_serial_backpressure_does_not_hoard_global_permit_while_mailbox_is_full() -> None:
    runtime = build_execution_concurrency_runtime(
        concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            default_queue_capacity=1,
        ),
        admission_budget=AdmissionBudget(
            max_total_in_flight=3,
            max_in_flight_per_group=3,
            max_blocking_io_in_flight=1,
            max_serial_in_flight=3,
        ),
    )
    serial_group = runtime.open_task_group("serial-pressure", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    other_group = runtime.open_task_group("other", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    release = Event()
    running = Event()

    def hold(context: TaskContextPort) -> None:
        running.set()
        release.wait(2)
        context.checkpoint()

    first = _serial(serial_group, "tiny", "s1", hold, capacity=1)
    assert running.wait(1)
    queued = _serial(serial_group, "tiny", "s2", lambda context: None, capacity=1)

    # A third SERIAL submit is forced to retry the full mailbox.  It must release
    # any global permit between retries so unrelated work can still enter.
    from threading import Thread
    third_done = Event()
    third_error: list[BaseException] = []

    def submit_third() -> None:
        try:
            _serial(serial_group, "tiny", "s3", lambda context: None, capacity=1)
        except BaseException as exc:
            third_error.append(exc)
        finally:
            third_done.set()

    waiter = Thread(target=submit_third)
    waiter.start()
    time.sleep(0.05)
    other = _blocking(other_group, "other-1", lambda context: 7, deadline=Deadline.after(0.5))
    assert other.result(1) == 7

    release.set()
    assert first.result(1) is None
    assert queued.result(1) is None
    assert third_done.wait(1)
    assert third_error == []
    waiter.join(1)
    serial_group.close()
    other_group.close()
    runtime.close()


def test_global_backpressure_skips_group_blocked_waiter_without_head_of_line_stall() -> None:
    runtime = build_execution_concurrency_runtime(
        concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=3,
            max_blocking_io_in_flight=3,
            max_cpu_workers=1,
            default_queue_capacity=4,
        ),
        admission_budget=AdmissionBudget(
            max_total_in_flight=2,
            max_in_flight_per_group=1,
            max_blocking_io_in_flight=2,
        ),
    )
    group_a = runtime.open_task_group("fair-a", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    group_b = runtime.open_task_group("fair-b", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    release_a = Event()
    started_a = Event()

    def hold(context: TaskContextPort) -> None:
        started_a.set()
        release_a.wait(2)
        context.checkpoint()

    first = _blocking(group_a, "fair-a-1", hold)
    assert started_a.wait(1)

    from threading import Thread
    waiter_done = Event()
    waiter_handles = []

    def queue_same_group() -> None:
        waiter_handles.append(_blocking(group_a, "fair-a-2", lambda context: None))
        waiter_done.set()

    waiter = Thread(target=queue_same_group)
    waiter.start()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and runtime.admission_snapshot().waiting != 1:
        time.sleep(0.002)
    snapshot = runtime.admission_snapshot()
    assert snapshot.waiting == 1
    assert {row.group_id: row.waiting for row in snapshot.groups}["fair-a"] == 1

    # Global capacity still has one slot.  A's earlier waiter cannot use it due
    # to the per-group quota, so B must not be head-of-line blocked by A.
    other = _blocking(group_b, "fair-b-1", lambda context: 9, deadline=Deadline.after(0.5))
    assert other.result(1) == 9

    release_a.set()
    assert first.result(1) is None
    assert waiter_done.wait(1)
    assert waiter_handles[0].result(1) is None
    waiter.join(1)
    group_a.close()
    group_b.close()
    runtime.close()


def test_lane_backpressure_prevents_blocking_pool_queue_from_hoarding_global_capacity() -> None:
    runtime = build_execution_concurrency_runtime(
        concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            default_queue_capacity=4,
        ),
        admission_budget=AdmissionBudget(
            max_total_in_flight=2,
            max_in_flight_per_group=2,
            max_blocking_io_in_flight=1,
            max_async_io_in_flight=2,
        ),
    )
    blocking_group = runtime.open_task_group(
        "lane-blocking",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
        admission_mode=AdmissionMode.REJECT,
    )
    async_group = runtime.open_task_group("lane-async", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    release = Event()
    started = Event()

    def hold(context: TaskContextPort) -> None:
        started.set()
        release.wait(2)
        context.checkpoint()

    first = _blocking(blocking_group, "hold", hold)
    assert started.wait(1)
    with pytest.raises(AdmissionRejected):
        blocking_group.submit(
            ExecutionSpec(
                task_id="queued-blocking-reject",
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
            ),
            lambda context: None,
        )

    async def immediate(context: TaskContextPort) -> int:
        context.checkpoint()
        return 13

    other = _async_io(async_group, "async-still-admitted", immediate)
    assert other.result(1) == 13
    snapshot = runtime.admission_snapshot()
    lanes = {row.lane_kind: row for row in snapshot.lanes}
    assert lanes[ExecutionLaneKind.BLOCKING_IO].max_in_flight == 1
    assert lanes[ExecutionLaneKind.BLOCKING_IO].in_flight == 1
    assert lanes[ExecutionLaneKind.ASYNC_IO].in_flight == 0

    release.set()
    assert first.result(1) is None
    blocking_group.close()
    async_group.close()
    runtime.close()


def test_hierarchical_backpressure_enforces_tenant_and_resource_quotas() -> None:
    runtime = build_execution_concurrency_runtime(
        concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=4,
            max_blocking_io_in_flight=4,
            max_cpu_workers=1,
            default_queue_capacity=4,
        ),
        admission_budget=AdmissionBudget(
            max_total_in_flight=4,
            max_in_flight_per_group=2,
            max_in_flight_per_tenant=1,
            max_in_flight_per_resource=1,
            max_blocking_io_in_flight=4,
        ),
    )
    tenant_a_one = runtime.open_task_group("tenant-a-one", tenant_id="tenant-a", resource_id="gpu-0")
    tenant_a_two = runtime.open_task_group(
        "tenant-a-two",
        tenant_id="tenant-a",
        resource_id="gpu-1",
        admission_mode=AdmissionMode.REJECT,
    )
    tenant_b_same_resource_name = runtime.open_task_group(
        "tenant-b-one", tenant_id="tenant-b", resource_id="gpu-0"
    )
    release = Event()
    started = Event()

    def hold(context: TaskContextPort) -> None:
        started.set()
        release.wait(2)
        context.checkpoint()

    first = _blocking(tenant_a_one, "hold", hold)
    assert started.wait(1)
    with pytest.raises(AdmissionRejected):
        tenant_a_two.submit(
            ExecutionSpec(
                task_id="tenant-quota-reject",
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
            ),
            lambda context: None,
        )

    # Resource identity is tenant-scoped: tenant-b/gpu-0 is distinct from
    # tenant-a/gpu-0 and can be admitted concurrently.
    other = _blocking(tenant_b_same_resource_name, "other", lambda context: 9)
    assert other.result(1) == 9
    snapshot = runtime.admission_snapshot()
    assert snapshot.max_in_flight_per_tenant == 1
    assert snapshot.max_in_flight_per_resource == 1
    assert {row.tenant_id for row in snapshot.tenants} == {"tenant-a"}
    assert any(row.tenant_id == "tenant-a" and row.resource_id == "gpu-0" for row in snapshot.resources)

    release.set()
    assert first.result(1) is None
    tenant_a_one.close()
    tenant_a_two.close()
    tenant_b_same_resource_name.close()
    runtime.close()


def test_priority_scheduler_runs_higher_priority_waiter_before_earlier_low_priority_waiter() -> None:
    from threading import Thread

    runtime = build_execution_concurrency_runtime(
        concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_blocking_io_in_flight=2,
            max_cpu_workers=1,
            default_queue_capacity=4,
        ),
        admission_budget=AdmissionBudget(
            max_total_in_flight=1,
            max_in_flight_per_group=1,
            max_blocking_io_in_flight=1,
        ),
        priority_aging_seconds=5.0,
    )
    blocker = runtime.open_task_group("priority-blocker")
    low = runtime.open_task_group("priority-low", priority=ExecutionPriority.LOW)
    high = runtime.open_task_group("priority-high", priority=ExecutionPriority.HIGH)
    release = Event()
    started = Event()
    order: list[str] = []
    handles: dict[str, object] = {}

    def hold(context: TaskContextPort) -> None:
        started.set()
        release.wait(2)
        context.checkpoint()

    first = _blocking(blocker, "hold", hold)
    assert started.wait(1)

    def submit(group, label: str) -> None:
        handles[label] = group.submit(
            ExecutionSpec(
                task_id=label,
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
            ),
            lambda context, name=label: order.append(name) or name,
        )

    low_thread = Thread(target=submit, args=(low, "low"))
    high_thread = Thread(target=submit, args=(high, "high"))
    low_thread.start()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and runtime.admission_snapshot().waiting < 1:
        time.sleep(0.002)
    high_thread.start()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and runtime.admission_snapshot().waiting < 2:
        time.sleep(0.002)
    assert runtime.admission_snapshot().waiting == 2

    release.set()
    assert first.result(1) is None
    low_thread.join(1)
    high_thread.join(1)
    assert handles["high"].result(1) == "high"
    assert handles["low"].result(1) == "low"
    assert order == ["high", "low"]
    blocker.close()
    low.close()
    high.close()
    runtime.close()


def test_same_priority_waiters_are_fair_across_groups_not_just_fifo_by_task() -> None:
    from threading import Thread

    runtime = build_execution_concurrency_runtime(
        concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_blocking_io_in_flight=2,
            max_cpu_workers=1,
            default_queue_capacity=8,
        ),
        admission_budget=AdmissionBudget(
            max_total_in_flight=1,
            max_in_flight_per_group=1,
            max_blocking_io_in_flight=1,
        ),
    )
    group_a = runtime.open_task_group("rr-a")
    group_b = runtime.open_task_group("rr-b")
    release = Event()
    started = Event()
    order: list[str] = []
    handles: list[object] = []

    def hold(context: TaskContextPort) -> None:
        started.set()
        release.wait(2)
        context.checkpoint()

    first = _blocking(group_a, "a-running", hold)
    assert started.wait(1)

    def queue(group, task_id: str) -> None:
        handles.append(_blocking(group, task_id, lambda context, value=task_id: order.append(value) or value))

    a2 = Thread(target=queue, args=(group_a, "a-2"))
    a3 = Thread(target=queue, args=(group_a, "a-3"))
    b1 = Thread(target=queue, args=(group_b, "b-1"))
    a2.start(); a3.start()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and runtime.admission_snapshot().waiting < 2:
        time.sleep(0.002)
    b1.start()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and runtime.admission_snapshot().waiting < 3:
        time.sleep(0.002)
    assert runtime.admission_snapshot().waiting == 3

    release.set()
    assert first.result(1) is None
    for thread in (a2, a3, b1):
        thread.join(1)
    for handle in handles:
        handle.result(1)
    # A received the previous grant, so B must receive the next grant even
    # though both A waiters have older FIFO tickets.
    assert order[0] == "b-1"
    group_a.close(); group_b.close(); runtime.close()


def test_serial_mailbox_coalescing_shares_one_physical_permit_and_survives_watcher_cancel() -> None:
    runtime = build_execution_concurrency_runtime(
        concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_serial_workers=1,
            max_cpu_workers=1,
            default_queue_capacity=2,
        ),
        admission_budget=AdmissionBudget(
            max_total_in_flight=2,
            max_in_flight_per_group=2,
            max_serial_in_flight=2,
        ),
    )
    group = runtime.open_task_group("coalesce", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    release = Event()
    started = Event()
    executed: list[int] = []

    def hold(context: TaskContextPort) -> None:
        started.set()
        release.wait(2)
        context.checkpoint()

    blocker = _serial(group, "coalesce-lane", "blocker", hold, capacity=2)
    assert started.wait(1)

    def update(context: TaskContextPort, value: int) -> int:
        context.checkpoint()
        executed.append(value)
        return value

    first = group.submit(
        ExecutionSpec(
            task_id="update-1",
            lane_kind=ExecutionLaneKind.SERIAL,
            lane_id="coalesce-lane",
            capacity=2,
            mailbox_policy=SerialMailboxPolicy.COALESCE,
            coalesce_key="latest-state",
        ),
        update,
        1,
    )
    second = group.submit(
        ExecutionSpec(
            task_id="update-2",
            lane_kind=ExecutionLaneKind.SERIAL,
            lane_id="coalesce-lane",
            capacity=2,
            mailbox_policy=SerialMailboxPolicy.COALESCE,
            coalesce_key="latest-state",
        ),
        update,
        2,
    )
    assert runtime.admission_snapshot().in_flight == 2
    assert first.cancel()
    # Cancelling one logical watcher cannot release the physical mailbox item's
    # lease while another coalesced watcher still depends on that execution.
    assert runtime.admission_snapshot().in_flight == 2

    release.set()
    assert blocker.result(1) is None
    assert second.result(1) == 2
    with pytest.raises(TaskCancelled):
        first.result(1)
    assert executed == [2]
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and runtime.admission_snapshot().in_flight:
        time.sleep(0.002)
    assert runtime.admission_snapshot().in_flight == 0
    group.close()
    runtime.close()
