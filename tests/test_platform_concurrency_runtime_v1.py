from __future__ import annotations

from pathlib import Path
from threading import Event
import asyncio
import gc
import os
import time

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    HeartbeatSpec,
    ScheduledTaskSpec,
    TaskCancelled,
    TaskContextPort,
    TaskDeadlineExceeded,
    TaskFailurePolicy,
    TaskState,
)
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.foundation.kernel.concurrency.providers import (
    AsyncIoExecutor,
    BoundedThreadExecutor,
    HeapTimerScheduler,
    SharedSerialExecutionLaneFactory,
)
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import InterprocessFileLock, InterprocessLockBusy




def _blocking(group, task_id: str, fn, /, *args, deadline=None, **kwargs):
    return group.submit(
        ExecutionSpec(task_id=task_id, lane_kind=ExecutionLaneKind.BLOCKING_IO),
        fn,
        *args,
        deadline=deadline,
        **kwargs,
    )


def _cpu(group, task_id: str, fn, /, *args, deadline=None, **kwargs):
    return group.submit(
        ExecutionSpec(task_id=task_id, lane_kind=ExecutionLaneKind.CPU),
        fn,
        *args,
        deadline=deadline,
        **kwargs,
    )


def _serial(group, lane_id: str, task_id: str, fn, /, *args, deadline=None, capacity=None, **kwargs):
    return group.submit(
        ExecutionSpec(
            task_id=task_id,
            lane_kind=ExecutionLaneKind.SERIAL,
            lane_id=lane_id,
            capacity=capacity,
        ),
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

def _cpu_square(value: int) -> int:
    return value * value


def _runtime(*, io_workers: int = 2):
    return build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=io_workers,
            max_cpu_workers=1,
            default_queue_capacity=8,
        ),
        blocking_io_thread_name_prefix="structured-test-io",
        timer_name="structured-test-timer",
    )


def test_provider_bounded_executor_applies_admission_backpressure_and_closes() -> None:
    release = Event()
    started = Event()
    executor = BoundedThreadExecutor(max_workers=1, max_in_flight=1, thread_name_prefix="test-io")

    def blocking():
        started.set()
        release.wait(2)
        return 7

    first = executor.submit(blocking)
    assert started.wait(1)
    with pytest.raises(TimeoutError):
        executor.submit(lambda: 8, deadline=Deadline.after(0.02))
    release.set()
    assert first.result(1) == 7
    executor.close()
    with pytest.raises(RuntimeError):
        executor.submit(lambda: 1)


def test_provider_serial_lane_preserves_order_with_bounded_mailbox() -> None:
    factory = SharedSerialExecutionLaneFactory(max_workers=1)
    lane = factory.create("actor-a", capacity=4)
    seen: list[int] = []
    handles = [lane.submit(lambda value=i: seen.append(value) or value) for i in range(4)]
    assert [handle.result(1) for handle in handles] == [0, 1, 2, 3]
    assert seen == [0, 1, 2, 3]
    lane.close()
    factory.close()


def test_provider_timer_scheduler_uses_one_owned_worker_for_many_tasks_and_surfaces_failure() -> None:
    scheduler = HeapTimerScheduler(name="timer-test")
    hit_a = Event()
    hit_b = Event()
    a = scheduler.schedule_fixed_delay(ScheduledTaskSpec("a", 0.02, 0.0), lambda: hit_a.set())
    b = scheduler.schedule_fixed_delay(ScheduledTaskSpec("b", 0.02, 0.0), lambda: hit_b.set())
    assert hit_a.wait(1) and hit_b.wait(1)
    a.assert_healthy()
    b.assert_healthy()
    a.cancel()
    b.cancel()
    scheduler.close()


def test_provider_timer_scheduler_marks_callback_failure_without_killing_scheduler() -> None:
    scheduler = HeapTimerScheduler(name="timer-failure-test")

    def boom():
        raise ValueError("boom")

    handle = scheduler.schedule_fixed_delay(ScheduledTaskSpec("bad", 0.02, 0.0), boom)
    deadline = time.time() + 1
    while time.time() < deadline:
        try:
            handle.assert_healthy()
        except Exception as exc:
            assert "boom" in str(exc)
            break
        time.sleep(0.01)
    else:
        pytest.fail("scheduled failure was not surfaced")
    scheduler.close()


def test_task_group_owns_blocking_cpu_and_serial_tasks_in_one_topology() -> None:
    runtime = _runtime()
    group = runtime.open_task_group("run-1", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    seen: list[str] = []

    def blocking(context: TaskContextPort, value: int) -> int:
        context.checkpoint()
        seen.append(context.task_id)
        return value + 1

    def serial(context: TaskContextPort, value: int) -> int:
        context.checkpoint()
        seen.append(context.task_id)
        return value + 2

    try:
        blocking_handle = _blocking(group, "blocking-a", blocking, 4)
        serial_handle = _serial(group, "agent-a", "serial-a", serial, 5, capacity=8)
        cpu_handle = _cpu(group, "cpu-a", _cpu_square, 6)
        assert blocking_handle.result(2) == 5
        assert serial_handle.result(2) == 7
        assert cpu_handle.result(5) == 36
        snapshot = runtime.topology_snapshot()
        assert tuple(item.group_id for item in snapshot.groups) == ("run-1",)
        tasks = {item.task_id: item for item in snapshot.groups[0].tasks}
        assert set(tasks) == {"blocking-a", "serial-a", "cpu-a"}
        assert all(item.state is TaskState.SUCCEEDED for item in tasks.values())
        assert snapshot.serial_lanes[0].owner_group_id == "run-1"
        assert snapshot.serial_lanes[0].capacity == 8
        assert set(seen) == {"blocking-a", "serial-a"}
    finally:
        runtime.close()


def test_group_cancellation_propagates_cooperatively_to_running_blocking_task() -> None:
    runtime = _runtime(io_workers=1)
    group = runtime.open_task_group("cancel-run")
    started = Event()

    def cooperative(context: TaskContextPort) -> None:
        started.set()
        while True:
            context.wait(0.01)
            context.checkpoint()

    handle = _blocking(group, "cooperative", cooperative)
    assert started.wait(1)
    group.cancel("operator requested stop")
    with pytest.raises(TaskCancelled, match="operator requested stop"):
        handle.result(2)
    group.close()
    snapshot = runtime.topology_snapshot()
    assert snapshot.groups[0].cancelled
    assert snapshot.groups[0].tasks[0].state is TaskState.CANCELLED
    runtime.close()


def test_deadline_failure_is_terminal_and_task_id_is_never_reused() -> None:
    runtime = _runtime(io_workers=1)
    group = runtime.open_task_group("deadline-run", failure_policy=TaskFailurePolicy.COLLECT_ALL)

    def too_slow(context: TaskContextPort) -> None:
        time.sleep(0.04)
        context.checkpoint()

    handle = _blocking(group, "deadline-task", too_slow, deadline=Deadline.after(0.01))
    with pytest.raises(TaskDeadlineExceeded):
        handle.result(1)
    assert handle.state is TaskState.FAILED
    with pytest.raises(ValueError, match="already owned"):
        _blocking(group, "deadline-task", lambda context: None)
    with pytest.raises(ExceptionGroup):
        group.close()
    runtime.close()


def test_serial_lane_identity_is_never_reassigned_between_groups() -> None:
    runtime = _runtime()
    first = runtime.open_task_group("owner-a")
    handle = _serial(first, "shared-authority", "one", lambda context: 1, capacity=8)
    assert handle.result(1) == 1
    first.close()
    second = runtime.open_task_group("owner-b")
    with pytest.raises(ValueError, match="another task group"):
        _serial(second, "shared-authority", "two", lambda context: 2, capacity=8)
    snapshot = runtime.topology_snapshot()
    assert snapshot.serial_lanes[0].closed
    assert snapshot.serial_lanes[0].owner_group_id == "owner-a"
    runtime.close()


def test_periodic_serial_registration_is_long_lived_until_cancelled() -> None:
    runtime = _runtime()
    group = runtime.open_task_group("periodic")
    hit = Event()

    def periodic(context: TaskContextPort) -> None:
        context.checkpoint()
        hit.set()

    handle = runtime.heartbeats.register(
        group.group_id,
        HeartbeatSpec(
            heartbeat_id="periodic-task",
            lane_id="periodic-writer",
            interval_seconds=0.02,
            initial_delay_seconds=0.0,
            lane_capacity=8,
        ),
        periodic,
    )
    assert hit.wait(1)
    snapshot = group.snapshot()
    task = next(item for item in snapshot.tasks if item.task_id == "heartbeat:periodic-task")
    assert task.state is TaskState.RUNNING
    handle.cancel()
    task = next(item for item in group.snapshot().tasks if item.task_id == "heartbeat:periodic-task")
    assert task.state is TaskState.CANCELLED
    group.close()
    runtime.close()


def _cpu_sleep_and_return(delay: float, value: int) -> int:
    time.sleep(delay)
    return value


def _cpu_mark_started_sleep_and_return(started_path: str, delay: float, value: int) -> int:
    Path(started_path).touch()
    time.sleep(delay)
    return value


def test_timer_one_shot_executes_once_without_periodic_requeue() -> None:
    scheduler = HeapTimerScheduler(name="timer-one-shot-test")
    hit = Event()
    count = [0]

    def once() -> None:
        count[0] += 1
        hit.set()

    handle = scheduler.schedule_once("once", 0.01, once)
    assert hit.wait(1)
    time.sleep(0.05)
    handle.assert_healthy()
    assert count == [1]
    scheduler.close()


def test_group_deadline_cancels_running_cooperative_child_without_result_polling() -> None:
    runtime = _runtime(io_workers=1)
    group = runtime.open_task_group(
        "group-deadline",
        deadline=Deadline.after(0.08),
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    started = Event()

    def cooperative(context: TaskContextPort) -> None:
        started.set()
        while True:
            context.wait(0.01)
            context.checkpoint()

    handle = _blocking(group, "child", cooperative)
    assert started.wait(1)
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and not group.cancellation.cancelled:
        time.sleep(0.005)
    assert group.cancellation.cancelled
    assert "task group deadline exceeded" in (group.cancellation.reason or "")
    with pytest.raises(TaskCancelled):
        handle.result(1)
    snapshot = group.snapshot()
    assert snapshot.deadline_monotonic is not None
    assert snapshot.cancelled
    group.close()
    runtime.close()


def test_cpu_deadline_is_enforced_by_shared_timer_without_result_polling() -> None:
    runtime = _runtime()
    group = runtime.open_task_group("cpu-deadline", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    handle = _cpu(group,
        "slow-cpu",
        _cpu_sleep_and_return,
        0.25,
        9,
        deadline=Deadline.after(0.05),
    )
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and handle.state is not TaskState.FAILED:
        time.sleep(0.005)
    assert handle.state is TaskState.FAILED
    with pytest.raises(TaskDeadlineExceeded):
        handle.result(0.01)
    with pytest.raises(ExceptionGroup):
        group.close()
    runtime.close()


def test_fail_fast_failure_cancels_running_sibling_cooperatively() -> None:
    runtime = _runtime(io_workers=2)
    group = runtime.open_task_group("fail-fast")
    sibling_started = Event()

    def sibling(context: TaskContextPort) -> None:
        sibling_started.set()
        while True:
            context.wait(0.01)
            context.checkpoint()

    def boom(context: TaskContextPort) -> None:
        context.checkpoint()
        raise ValueError("boom")

    sibling_handle = _blocking(group, "sibling", sibling)
    assert sibling_started.wait(1)
    failing_handle = _blocking(group, "boom", boom)
    with pytest.raises(ValueError, match="boom"):
        failing_handle.result(1)
    with pytest.raises(TaskCancelled):
        sibling_handle.result(1)
    assert group.cancellation.cancelled
    with pytest.raises(ExceptionGroup):
        group.close()
    runtime.close()


def test_serial_lane_close_rejects_blocked_admission_without_orphan_future() -> None:
    from threading import Thread

    factory = SharedSerialExecutionLaneFactory(max_workers=1)
    lane = factory.create("close-admission-race", capacity=1)
    first_started = Event()
    release_first = Event()
    submit_finished = Event()
    close_finished = Event()
    third_holder: list[object] = []
    submit_errors: list[BaseException] = []
    close_errors: list[BaseException] = []

    def first() -> int:
        first_started.set()
        release_first.wait(2)
        return 1

    first_handle = lane.submit(first)
    assert first_started.wait(1)
    second_handle = lane.submit(lambda: 2)

    def submit_third() -> None:
        try:
            third_holder.append(lane.submit(lambda: 3, deadline=Deadline.after(1)))
        except BaseException as exc:
            submit_errors.append(exc)
        finally:
            submit_finished.set()

    def close_lane() -> None:
        try:
            lane.close()
        except BaseException as exc:
            close_errors.append(exc)
        finally:
            close_finished.set()

    submit_thread = Thread(target=submit_third)
    close_thread = Thread(target=close_lane)
    submit_thread.start()
    time.sleep(0.02)
    close_thread.start()

    # close() is the lifecycle linearization point. The third producer has not
    # been admitted yet, so it must be rejected rather than returning a future
    # that could sit behind shutdown with no owner left to execute it. Already
    # accepted work (first + second) is still drained by graceful close.
    assert submit_finished.wait(1)
    assert third_holder == []
    assert len(submit_errors) == 1
    assert isinstance(submit_errors[0], RuntimeError)
    assert "closed" in str(submit_errors[0])

    release_first.set()
    assert first_handle.result(1) == 1
    assert second_handle.result(1) == 2
    assert close_finished.wait(1)
    assert close_errors == []
    submit_thread.join(1)
    close_thread.join(1)
    factory.close()


def test_cancel_pending_lane_drains_published_ready_token_without_killing_worker() -> None:
    from threading import Thread

    factory = SharedSerialExecutionLaneFactory(max_workers=1, thread_name_prefix="serial-cancel-ready")
    blocker = factory.create("blocker", capacity=1)
    cancelled = factory.create("cancelled", capacity=1)
    survivor = factory.create("survivor", capacity=1)
    started = Event()
    release = Event()

    def hold_worker() -> None:
        started.set()
        release.wait(2)

    blocker_handle = blocker.submit(hold_worker)
    assert started.wait(1)
    cancelled_handle = cancelled.submit(lambda: 2)

    close_errors: list[BaseException] = []

    def close_cancelled() -> None:
        try:
            cancelled.close(cancel_pending=True, deadline=Deadline.after(1))
        except BaseException as exc:
            close_errors.append(exc)

    closer = Thread(target=close_cancelled)
    closer.start()
    time.sleep(0.02)
    assert cancelled_handle.cancelled()

    release.set()
    blocker_handle.result(1)
    closer.join(1)
    assert not closer.is_alive()
    assert close_errors == []

    # Consuming the cancelled lane's already-published ready token must be a
    # no-op, not a worker-fatal scheduled-state corruption.
    assert survivor.submit(lambda: 3).result(1) == 3
    blocker.close()
    survivor.close()
    factory.close()


def test_shared_serial_lane_is_pinned_to_one_worker_thread() -> None:
    from threading import get_ident

    factory = SharedSerialExecutionLaneFactory(max_workers=2, thread_name_prefix="serial-affinity-test")
    lane = factory.create("affine-lane", capacity=8)
    thread_ids = [lane.submit(get_ident).result(1) for _ in range(20)]
    assert len(set(thread_ids)) == 1
    lane.close()
    factory.close()


def test_shared_serial_factory_multiplexes_many_lanes_onto_fixed_workers() -> None:
    import threading

    prefix = "serial-multiplex-test"
    factory = SharedSerialExecutionLaneFactory(max_workers=2, thread_name_prefix=prefix)
    lanes = [factory.create(f"lane-{index}", capacity=2) for index in range(32)]
    handles = [lane.submit(lambda value=index: value) for index, lane in enumerate(lanes)]
    assert [handle.result(1) for handle in handles] == list(range(32))
    workers = [thread for thread in threading.enumerate() if thread.name.startswith(prefix + ":")]
    assert len(workers) == 2
    for lane in lanes:
        lane.close()
    factory.close()
    assert not [thread for thread in threading.enumerate() if thread.name.startswith(prefix + ":")]


def test_closed_group_cancels_its_deadline_registration() -> None:
    runtime = _runtime()
    group = runtime.open_task_group(
        "closed-before-deadline",
        deadline=Deadline.after(0.08),
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    group.close()
    time.sleep(0.12)
    snapshot = group.snapshot()
    assert snapshot.closed
    assert not snapshot.cancelled
    runtime.close()


def test_deadline_terminal_cause_wins_over_cooperative_cancellation_exception() -> None:
    runtime = _runtime(io_workers=1)
    group = runtime.open_task_group("deadline-cause")
    started = Event()

    def cooperative(context: TaskContextPort) -> None:
        started.set()
        while True:
            context.wait(1)
            context.checkpoint()

    handle = _blocking(group,
        "deadline-child",
        cooperative,
        deadline=Deadline.after(0.05),
    )
    assert started.wait(1)
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and handle.state is not TaskState.FAILED:
        time.sleep(0.005)
    assert handle.state is TaskState.FAILED
    with pytest.raises(TaskDeadlineExceeded):
        handle.result(1)
    with pytest.raises(ExceptionGroup):
        group.close()
    runtime.close()


def test_group_cancellation_interrupts_blocked_executor_admission() -> None:
    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            default_queue_capacity=4,
        ),
        blocking_io_thread_name_prefix="admission-cancel-io",
        timer_name="admission-cancel-timer",
    )
    group = runtime.open_task_group("admission-cancel", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    first_started = Event()
    release_first = Event()
    second_finished = Event()
    second_errors: list[BaseException] = []

    def first(context: TaskContextPort) -> None:
        first_started.set()
        release_first.wait(2)
        context.checkpoint()

    first_handle = _blocking(group, "first", first)
    assert first_started.wait(1)

    def submit_second() -> None:
        try:
            _blocking(group, "second", lambda context: None)
        except BaseException as exc:
            second_errors.append(exc)
        finally:
            second_finished.set()

    from threading import Thread

    submitter = Thread(target=submit_second)
    submitter.start()
    time.sleep(0.05)
    group.cancel("cancel blocked admission")
    assert second_finished.wait(0.5)
    assert len(second_errors) == 1
    assert isinstance(second_errors[0], TaskCancelled)
    snapshot = group.snapshot()
    states = {item.task_id: item.state for item in snapshot.tasks}
    assert states["second"] is TaskState.CANCELLED
    release_first.set()
    with pytest.raises(TaskCancelled):
        first_handle.result(1)
    submitter.join(1)
    group.close()
    runtime.close()


def test_group_cancellation_interrupts_blocking_executor_admission() -> None:
    from threading import Thread

    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            default_queue_capacity=4,
            shutdown_timeout_seconds=2,
        ),
        blocking_io_thread_name_prefix="admission-cancel-io",
        timer_name="admission-cancel-timer",
    )
    group = runtime.open_task_group("admission-cancel")
    started = Event()
    release = Event()
    second_done = Event()
    second_error: list[BaseException] = []

    def first(context: TaskContextPort) -> None:
        started.set()
        release.wait(2)
        context.checkpoint()

    first_handle = _blocking(group, "first", first)
    assert started.wait(1)

    def submit_second() -> None:
        try:
            _blocking(group, "second", lambda context: None)
        except BaseException as exc:
            second_error.append(exc)
        finally:
            second_done.set()

    thread = Thread(target=submit_second)
    thread.start()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if any(task.task_id == "second" for task in group.snapshot().tasks):
            break
        time.sleep(0.005)
    else:
        pytest.fail("second task never entered structured admission")

    group.cancel("cancel saturated admission")
    assert second_done.wait(0.5)
    assert len(second_error) == 1
    assert isinstance(second_error[0], TaskCancelled)
    release.set()
    thread.join(1)
    with pytest.raises(TaskCancelled):
        first_handle.result(1)
    group.close()
    runtime.close()


def test_running_cpu_child_joins_then_remains_cancelled_not_false_success(tmp_path: Path) -> None:
    runtime = _runtime()
    group = runtime.open_task_group("cpu-cancel")
    started = tmp_path / "cpu-started"
    handle = _cpu(group, "cpu", _cpu_mark_started_sleep_and_return, str(started), 0.15, 11)

    # ProcessPool futures can become logically RUNNING while work is still queued
    # for a worker.  Wait for evidence from inside the child so this test actually
    # exercises non-preemptive cancellation of a physically running CPU task.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not started.exists():
        time.sleep(0.005)
    assert started.exists(), "CPU child never reached physical execution"

    group.cancel("cancel running cpu")
    with pytest.raises(TaskCancelled):
        handle.result(2)
    assert handle.state is TaskState.CANCELLED
    group.close()
    runtime.close()


def test_task_group_close_cancels_blocked_admission_and_leaves_no_orphan_child() -> None:
    from threading import Thread

    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            default_queue_capacity=4,
        ),
        blocking_io_thread_name_prefix="admission-close-io",
        timer_name="admission-close-timer",
    )
    group = runtime.open_task_group("admission-close")
    started = Event()
    submit_finished = Event()
    close_finished = Event()
    submit_errors: list[BaseException] = []
    close_errors: list[BaseException] = []

    def cooperative(context: TaskContextPort) -> None:
        started.set()
        while True:
            context.wait(0.01)
            context.checkpoint()

    first = _blocking(group, "first", cooperative)
    assert started.wait(1)

    def blocked_submit() -> None:
        try:
            _blocking(group, "blocked", lambda context: 2)
        except BaseException as exc:
            submit_errors.append(exc)
        finally:
            submit_finished.set()

    def close_group() -> None:
        try:
            group.close(cancel_pending=True)
        except BaseException as exc:
            close_errors.append(exc)
        finally:
            close_finished.set()

    submit_thread = Thread(target=blocked_submit)
    close_thread = Thread(target=close_group)
    submit_thread.start()
    time.sleep(0.02)
    close_thread.start()

    assert submit_finished.wait(2)
    assert close_finished.wait(2)
    submit_thread.join(1)
    close_thread.join(1)
    assert len(submit_errors) == 1
    assert isinstance(submit_errors[0], TaskCancelled)
    assert close_errors == []
    with pytest.raises(TaskCancelled):
        first.result(1)
    snapshot = group.snapshot()
    assert snapshot.closed
    assert snapshot.converged
    assert all(task.execution_done for task in snapshot.tasks)
    runtime.close()


def test_cpu_deadline_distinguishes_logical_failure_from_physical_completion() -> None:
    runtime = _runtime()
    group = runtime.open_task_group(
        "cpu-physical-liveness",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    handle = _cpu(group,
        "slow",
        _cpu_sleep_and_return,
        0.30,
        5,
        deadline=Deadline.after(0.05),
    )
    deadline = time.monotonic() + 1
    task = group.snapshot().tasks[0]
    while time.monotonic() < deadline and task.state is not TaskState.FAILED:
        time.sleep(0.005)
        task = group.snapshot().tasks[0]
    assert task.state is TaskState.FAILED
    assert task.failure_type == "TaskDeadlineExceeded"
    assert not task.execution_done
    assert not handle.done()
    with pytest.raises(TaskDeadlineExceeded):
        handle.result(0)
    with pytest.raises(ExceptionGroup):
        group.close()
    task = group.snapshot().tasks[0]
    assert task.execution_done
    assert group.snapshot().converged
    runtime.close()


def test_runtime_concurrent_close_waits_for_single_shutdown_authority() -> None:
    from threading import Thread

    runtime = _runtime(io_workers=1)
    group = runtime.open_task_group("runtime-close-race")
    started = Event()
    close_results: list[str] = []
    close_errors: list[BaseException] = []

    def cooperative(context: TaskContextPort) -> None:
        started.set()
        while True:
            context.wait(0.01)
            context.checkpoint()

    _blocking(group, "child", cooperative)
    assert started.wait(1)

    def close_runtime(label: str) -> None:
        try:
            runtime.close()
        except BaseException as exc:
            close_errors.append(exc)
        else:
            close_results.append(label)

    a = Thread(target=close_runtime, args=("a",))
    b = Thread(target=close_runtime, args=("b",))
    a.start()
    b.start()
    a.join(2)
    b.join(2)
    assert not a.is_alive() and not b.is_alive()
    assert close_errors == []
    assert sorted(close_results) == ["a", "b"]
    snapshot = runtime.topology_snapshot()
    assert snapshot.closed
    assert not snapshot.closing
    assert snapshot.groups[0].converged


def test_child_checkpoint_propagates_inherited_group_deadline_when_timer_is_delayed() -> None:
    runtime = _runtime(io_workers=2)
    timer_blocked = Event()
    release_timer = Event()

    def jam_timer() -> None:
        timer_blocked.set()
        release_timer.wait(2)

    # Deliberately occupy the single timer worker so the child, rather than the
    # group watchdog, is the first observer of the scope deadline.
    runtime._timers.schedule_once("test-delayed-group-watchdog", 0.0, jam_timer)
    assert timer_blocked.wait(1)
    # Give task submission a scheduling-independent setup window. The semantic
    # condition under test is that a running child observes the inherited group
    # deadline before the deliberately blocked watchdog, not that two submits
    # happen to complete within a few tens of milliseconds on a loaded host.
    group = runtime.open_task_group(
        "deadline-observed-by-child",
        deadline=Deadline.after(1.0),
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    sibling_started = Event()

    def sibling(context: TaskContextPort) -> None:
        sibling_started.set()
        context.wait(1)
        context.checkpoint()

    def observer(context: TaskContextPort) -> None:
        time.sleep(1.1)
        context.checkpoint()

    sibling_handle = _blocking(group, "sibling", sibling)
    observer_handle = _blocking(group, "observer", observer)
    assert sibling_started.wait(1)
    try:
        with pytest.raises(TaskCancelled):
            observer_handle.result(1)
        with pytest.raises(TaskCancelled):
            sibling_handle.result(1)
        snapshot = group.snapshot()
        states = {task.task_id: task.state for task in snapshot.tasks}
        assert snapshot.cancelled
        assert "task group deadline exceeded" in (snapshot.cancellation_reason or "")
        assert states == {
            "observer": TaskState.CANCELLED,
            "sibling": TaskState.CANCELLED,
        }
        assert all(task.failure_type is None for task in snapshot.tasks)
    finally:
        release_timer.set()
        try:
            group.close()
        finally:
            runtime.close()


def test_recurring_registration_after_inherited_group_deadline_is_cancelled_not_failed() -> None:
    runtime = _runtime()
    timer_blocked = Event()
    release_timer = Event()

    def jam_timer() -> None:
        timer_blocked.set()
        release_timer.wait(2)

    runtime._timers.schedule_once("test-delayed-recurring-group-watchdog", 0.0, jam_timer)
    assert timer_blocked.wait(1)
    group = runtime.open_task_group(
        "expired-recurring-group",
        deadline=Deadline.after(0.03),
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    time.sleep(0.06)
    try:
        with pytest.raises(TaskCancelled):
            runtime.heartbeats.register(
                group.group_id,
                HeartbeatSpec(
                    heartbeat_id="periodic",
                    lane_id="expired-recurring-lane",
                    interval_seconds=1.0,
                ),
                lambda context: context.checkpoint(),
            )
        snapshot = group.snapshot()
        task = next(item for item in snapshot.tasks if item.task_id == "heartbeat:periodic")
        assert snapshot.cancelled
        assert task.state is TaskState.CANCELLED
        assert task.failure_type is None
    finally:
        release_timer.set()
        try:
            group.close()
        finally:
            runtime.close()


def test_runtime_shutdown_reports_sealed_but_not_converged_and_can_retry_join() -> None:
    runtime = _runtime(io_workers=1)
    group = runtime.open_task_group(
        "retry-runtime-convergence",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    started = Event()
    release = Event()

    def non_cooperative(context: TaskContextPort) -> None:
        started.set()
        release.wait(2)

    _blocking(group, "non-cooperative", non_cooperative)
    assert started.wait(1)

    with pytest.raises(ExceptionGroup):
        runtime.close(deadline=Deadline.after(0.02))
    failed = runtime.topology_snapshot()
    assert failed.closed
    assert not failed.closing
    assert not failed.converged
    assert failed.shutdown_failure_type == "ExceptionGroup"
    assert not next(item for item in failed.groups if item.group_id == group.group_id).converged
    with pytest.raises(RuntimeError):
        runtime.open_task_group("must-remain-sealed")

    release.set()
    runtime.close(deadline=Deadline.after(2))
    recovered = runtime.topology_snapshot()
    assert recovered.closed
    assert recovered.converged
    assert recovered.shutdown_failure_type is None
    assert next(item for item in recovered.groups if item.group_id == group.group_id).converged


def test_group_deadline_stays_armed_while_close_joins_children() -> None:
    runtime = _runtime(io_workers=1)
    group = runtime.open_task_group(
        "deadline-during-close",
        deadline=Deadline.after(0.08),
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    started = Event()

    def cooperative(context: TaskContextPort) -> None:
        started.set()
        while True:
            context.wait(0.01)
            context.checkpoint()

    handle = _blocking(group, "child", cooperative)
    assert started.wait(1)
    started_close = time.monotonic()
    group.close(cancel_pending=False)
    elapsed = time.monotonic() - started_close

    # close seals admission but the group deadline remains authoritative until
    # accepted work converges, so this returns near the scope deadline instead of
    # falling through to the much larger runtime shutdown timeout.
    assert elapsed < 0.75
    assert group.cancellation.cancelled
    assert "task group deadline exceeded" in (group.cancellation.reason or "")
    with pytest.raises(TaskCancelled):
        handle.result(1)
    assert group.snapshot().converged
    runtime.close()


def test_group_owned_deadline_uses_one_timer_and_tighter_child_gets_one_more() -> None:
    runtime = _runtime(io_workers=2)
    group = runtime.open_task_group(
        "deadline-owner-count",
        deadline=Deadline.after(1.0),
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    release = Event()
    inherited_started = Event()
    child_started = Event()

    def wait_inherited(context: TaskContextPort) -> str:
        inherited_started.set()
        release.wait(1)
        context.checkpoint()
        return "inherited"

    def wait_child(context: TaskContextPort) -> str:
        child_started.set()
        release.wait(1)
        context.checkpoint()
        return "child"

    inherited = _blocking(group, "inherits-group", wait_inherited)
    assert inherited_started.wait(1)
    # Group deadline is registered once; inherited children do not clone it.
    assert runtime._timers.active_registration_count == 1

    tighter = _blocking(group,
        "tighter-child",
        wait_child,
        deadline=Deadline.after(0.5),
    )
    assert child_started.wait(1)
    assert runtime._timers.active_registration_count == 2

    release.set()
    assert inherited.result(1) == "inherited"
    assert tighter.result(1) == "child"
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and runtime._timers.active_registration_count != 1:
        time.sleep(0.005)
    assert runtime._timers.active_registration_count == 1
    group.close()
    assert runtime._timers.active_registration_count == 0
    runtime.close()


def test_periodic_serial_backpressure_never_blocks_shared_deadline_timer() -> None:
    runtime = _runtime(io_workers=1)
    group = runtime.open_task_group(
        "timer-must-not-block",
        deadline=Deadline.after(0.08),
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    blocker_started = Event()
    release = Event()

    def blocker(context: TaskContextPort) -> None:
        blocker_started.set()
        while not release.is_set():
            context.wait(0.01)
            context.checkpoint()

    first = _serial(group, "saturated-lane", "blocker", blocker, capacity=1)
    assert blocker_started.wait(1)
    queued = _serial(group, "saturated-lane", "queued", lambda context: 1, capacity=1)
    periodic = runtime.heartbeats.register(
        group.group_id,
        HeartbeatSpec(
            heartbeat_id="periodic-under-pressure",
            lane_id="saturated-lane",
            interval_seconds=0.01,
            initial_delay_seconds=0.0,
            lane_capacity=1,
        ),
        lambda context: None,
    )
    try:
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and not group.cancellation.cancelled:
            time.sleep(0.005)
        assert group.cancellation.cancelled
        assert "task group deadline exceeded" in (group.cancellation.reason or "")
        with pytest.raises(TaskCancelled):
            first.result(0.1)
    finally:
        release.set()
        periodic.cancel()
    # The queued child was accepted before the scope deadline but must not escape
    # structured cancellation simply because the serial owner was saturated.
    with pytest.raises(TaskCancelled):
        queued.result(1)
    group.close()
    runtime.close()


def test_timer_compacts_cancelled_deadline_tombstones_and_never_reuses_identity() -> None:
    scheduler = HeapTimerScheduler(name="timer-compaction-test")
    handles = [
        scheduler.schedule_once(f"far-future-{index}", 60.0, lambda: None)
        for index in range(160)
    ]
    for handle in handles[:120]:
        handle.cancel()
    # The rebuild threshold is deliberately amortized, but a majority of dead
    # entries must not remain pinned for their original 60-second deadlines.
    assert len(scheduler._heap) < 100
    assert scheduler.active_registration_count == 40
    with pytest.raises(ValueError, match="scheduler lifetime"):
        scheduler.schedule_once("far-future-0", 1.0, lambda: None)
    scheduler.close()


def test_runtime_convergence_is_physical_even_when_child_failure_is_reported() -> None:
    runtime = _runtime(io_workers=1)
    group = runtime.open_task_group(
        "logical-failure-physical-convergence",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )

    def boom(context: TaskContextPort) -> None:
        context.checkpoint()
        raise ValueError("logical child failure")

    handle = _blocking(group, "boom", boom)
    with pytest.raises(ValueError, match="logical child failure"):
        handle.result(1)

    # The runtime must still report the logical shutdown failure, but convergence
    # is a structural fact: all owned tasks, timers, lanes, threads and processes
    # have physically joined. It must not depend on whether group.close() happened
    # to be called separately before runtime.close().
    with pytest.raises(ExceptionGroup):
        runtime.close()
    snapshot = runtime.topology_snapshot()
    assert snapshot.closed
    assert snapshot.converged
    assert snapshot.shutdown_failure_type == "ExceptionGroup"
    owned = next(item for item in snapshot.groups if item.group_id == group.group_id)
    assert owned.converged
    assert owned.tasks[0].state is TaskState.FAILED


def test_unified_heartbeat_scheduler_is_process_wide_and_topology_visible() -> None:
    runtime = _runtime()
    group = runtime.open_task_group("heartbeat-topology")
    hit = Event()

    handle = runtime.heartbeats.register(
        group.group_id,
        HeartbeatSpec(
            heartbeat_id="lease-renewal-a",
            lane_id="lease-writer-a",
            interval_seconds=0.02,
            initial_delay_seconds=0.0,
            lane_capacity=4,
        ),
        lambda context: hit.set(),
    )
    assert hit.wait(1)
    snapshot = runtime.topology_snapshot()
    assert len(snapshot.heartbeats) == 1
    heartbeat = snapshot.heartbeats[0]
    assert heartbeat.heartbeat_id == "lease-renewal-a"
    assert heartbeat.owner_group_id == group.group_id
    assert heartbeat.lane_id == "lease-writer-a"
    assert heartbeat.active
    with pytest.raises(ValueError, match="runtime lifetime"):
        runtime.heartbeats.register(
            group.group_id,
            HeartbeatSpec(
                heartbeat_id="lease-renewal-a",
                lane_id="another-lane",
                interval_seconds=1.0,
            ),
            lambda context: None,
        )
    handle.cancel()
    assert not runtime.topology_snapshot().heartbeats[0].active
    runtime.close()


def test_async_io_lane_is_owned_by_task_group_and_deadline_cancels_coroutine() -> None:
    runtime = _runtime()
    group = runtime.open_task_group(
        "async-io-owned",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )

    async def quick(context: TaskContextPort, value: int) -> int:
        context.checkpoint()
        return value + 1

    async def cooperative(context: TaskContextPort) -> None:
        while True:
            await __import__("asyncio").sleep(0.005)
            context.checkpoint()

    fast = _async_io(group, "async-fast", quick, 4)
    assert fast.result(1) == 5
    snapshot = group.snapshot()
    fast_task = next(item for item in snapshot.tasks if item.task_id == "async-fast")
    assert fast_task.lane_kind is ExecutionLaneKind.ASYNC_IO
    assert fast_task.state is TaskState.SUCCEEDED

    timed = _async_io(
        group,
        "async-deadline",
        cooperative,
        deadline=Deadline.after(0.04),
    )
    with pytest.raises(TaskDeadlineExceeded):
        timed.result(1)
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and not timed.done():
        time.sleep(0.005)
    assert timed.done()
    with pytest.raises(ExceptionGroup):
        group.close()
    runtime.close()


def test_async_io_snapshot_reports_running_after_coroutine_enters() -> None:
    runtime = _runtime()
    group = runtime.open_task_group(
        "async-io-running-state",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    started = Event()
    release = Event()

    async def blocked(context: TaskContextPort) -> int:
        started.set()
        while not release.is_set():
            await __import__("asyncio").sleep(0.005)
            context.checkpoint()
        return 7

    handle = _async_io(group, "async-running", blocked)
    try:
        assert started.wait(1)
        task = next(item for item in group.snapshot().tasks if item.task_id == "async-running")
        assert task.state is TaskState.RUNNING
        assert not task.execution_done
        release.set()
        assert handle.result(1) == 7
        assert next(
            item for item in group.snapshot().tasks if item.task_id == "async-running"
        ).state is TaskState.SUCCEEDED
    finally:
        release.set()
        runtime.close()


def test_async_io_capacity_releases_only_after_cancelled_source_physically_finishes() -> None:
    executor = AsyncIoExecutor(max_in_flight=1)
    started = Event()
    cleanup_started = Event()
    cleanup_done = Event()
    second_started = Event()

    async def cancellation_cleanup() -> int:
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cleanup_started.set()
            await asyncio.sleep(0.12)
            cleanup_done.set()
            raise

    async def second() -> int:
        second_started.set()
        return 2

    first = executor.submit(cancellation_cleanup)
    try:
        assert started.wait(1)
        assert first.cancel()
        assert cleanup_started.wait(1)
        with pytest.raises(TimeoutError, match="capacity wait deadline expired"):
            executor.submit(second, deadline=Deadline.after(0.03))
        assert not second_started.is_set()
        assert cleanup_done.wait(1)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and not first.done():
            time.sleep(0.002)
        assert first.done() and first.cancelled()
        followup = executor.submit(second)
        assert followup.result(1) == 2
        assert second_started.is_set()
    finally:
        executor.close()


def test_async_io_provider_retrieves_source_exception_after_logical_cancel() -> None:
    executor = AsyncIoExecutor(max_in_flight=1)
    started = Event()
    handler_installed = Event()
    loop_errors: list[dict[str, object]] = []

    def install_handler() -> None:
        executor._loop.set_exception_handler(
            lambda _loop, context: loop_errors.append(dict(context))
        )
        handler_installed.set()

    executor._loop.call_soon_threadsafe(install_handler)
    assert handler_installed.wait(1)

    async def fail_after_cancellation_cleanup() -> None:
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0.02)
            raise TaskCancelled("source cleanup terminal exception")

    handle = executor.submit(fail_after_cancellation_cleanup)
    assert started.wait(1)
    assert handle.cancel()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and not handle.done():
        time.sleep(0.002)
    assert handle.done()
    # Do not retrieve the proxy result: the provider must still own/retrieve the
    # source asyncio Task exception independently of caller result consumption.
    executor.close()
    del handle
    gc.collect()
    assert not [
        row for row in loop_errors
        if row.get("message") == "Task exception was never retrieved"
    ]


def test_async_io_waiting_close_joins_prior_nonblocking_shutdown() -> None:
    executor = AsyncIoExecutor(max_in_flight=1)
    started = Event(); cleanup_started = Event(); cleanup_done = Event()
    loop_errors: list[dict[str, object]] = []
    executor._loop.call_soon_threadsafe(
        executor._loop.set_exception_handler,
        lambda _loop, context: loop_errors.append(dict(context)),
    )
    async def job() -> None:
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cleanup_started.set(); await asyncio.sleep(0.08); cleanup_done.set(); raise
    executor.submit(job)
    assert started.wait(1)
    executor.close(wait=False, cancel_pending=True)
    assert cleanup_started.wait(1)
    executor.close(wait=True, cancel_pending=True)
    gc.collect()
    assert cleanup_done.is_set()
    assert not executor._thread.is_alive()
    assert not [row for row in loop_errors if row.get("message") == "Task was destroyed but it is pending!"]


def test_async_io_executor_releases_fast_completion_admission_without_tracking_leak() -> None:
    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            max_async_io_in_flight=1,
            default_queue_capacity=2,
        )
    )
    group = runtime.open_task_group("async-fast-race", failure_policy=TaskFailurePolicy.COLLECT_ALL)

    async def immediate(context: TaskContextPort, value: int) -> int:
        return value

    for value in range(100):
        assert _async_io(group, f"fast-{value}", immediate, value).result(1) == value
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        with runtime._async_io._condition:
            if not runtime._async_io._futures and runtime._async_io._available == 1:
                break
        time.sleep(0.002)
    with runtime._async_io._condition:
        assert not runtime._async_io._futures
        assert runtime._async_io._available == 1
    runtime.close()






def test_serial_actor_request_failure_is_caller_owned_and_does_not_poison_scope() -> None:
    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            default_queue_capacity=4,
        )
    )
    group = runtime.open_task_group("actor-failure-scope", failure_policy=TaskFailurePolicy.FAIL_FAST)
    actor = group.open_serial_actor("writer", lane_id="writer-lane")

    def fail() -> None:
        raise ValueError("owned request failed")

    with pytest.raises(ValueError, match="owned request failed"):
        actor.call("fail", fail)

    assert not group.cancellation.cancelled
    snapshot = group.snapshot()
    failed = [task for task in snapshot.tasks if task.state is TaskState.FAILED]
    assert len(failed) == 1
    assert failed[0].failure_scope.value == "caller"
    assert actor.call("recover", lambda: 7) == 7

    group.close()
    runtime.close()


def test_failed_recurring_task_retires_timer_registration() -> None:
    runtime = _runtime()
    group = runtime.open_task_group(
        "recurring-failure-retirement",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    attempts: list[int] = []

    def boom(context: TaskContextPort) -> None:
        context.checkpoint()
        attempts.append(1)
        raise ValueError("recurring-boom")

    handle = runtime.heartbeats.register(
        group.group_id,
        HeartbeatSpec(
            heartbeat_id="failing-recurring",
            lane_id="failing-recurring-lane",
            interval_seconds=0.01,
            initial_delay_seconds=0.0,
            lane_capacity=4,
        ),
        boom,
    )
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            handle.assert_healthy()
        except RuntimeError as exc:
            assert "recurring-boom" in str(exc)
            break
        time.sleep(0.005)
    else:
        pytest.fail("recurring task failure was not surfaced")

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and runtime._timers.active_registration_count:
        time.sleep(0.005)
    assert attempts
    assert runtime._timers.active_registration_count == 0
    with pytest.raises(ExceptionGroup):
        group.close()
    runtime.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows path namespace identity is platform-specific")
def test_windows_interprocess_lock_unifies_extended_length_path_alias(tmp_path: Path) -> None:
    ordinary = tmp_path / "guard.lock"
    ordinary.touch()
    extended = Path("\\\\?\\" + str(ordinary.resolve(strict=False)))

    ordinary_name = InterprocessFileLock(ordinary)._windows_mutex_name()
    extended_name = InterprocessFileLock(extended)._windows_mutex_name()

    assert ordinary_name == extended_name
    with InterprocessFileLock(ordinary):
        with pytest.raises(InterprocessLockBusy):
            with InterprocessFileLock(extended, blocking=False):
                raise AssertionError("equivalent Windows path alias entered a second lock domain")

def test_deadline_residual_cancel_surfaces_logical_deadline_failure() -> None:
    from concurrent.futures import CancelledError
    from types import SimpleNamespace
    from noetrium_platform.foundation.kernel.concurrency.runtime.cancellation import _DeadlineOwner
    from noetrium_platform.foundation.kernel.concurrency.runtime.task_handles import _OwnedTaskHandle

    failure = TaskDeadlineExceeded("task deadline exceeded: race-group/race-task")

    class ResidualCancelledRaw:
        def __init__(self) -> None:
            self.calls = 0

        def result(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError
            raise CancelledError

    raw = ResidualCancelledRaw()

    class FakeGroup:
        group_id = "race-group"
        cancellation = SimpleNamespace(reason=None)

        def _task_failure(self, task_id: str):
            return failure if raw.calls >= 1 else None

        def _bounded_wait_timeout(self, deadline, timeout):
            return 0.001

        def _sync_terminal_from_raw(self, task_id: str) -> None:
            return None

    record = SimpleNamespace(
        raw_handle=raw, task_id="race-task", deadline=Deadline.after(1.0),
        deadline_owner=_DeadlineOwner.TASK, cancellation=SimpleNamespace(reason=None),
    )
    handle = _OwnedTaskHandle(FakeGroup(), record)
    with pytest.raises(TaskDeadlineExceeded, match="race-group/race-task"):
        handle.result(1.0)
    assert raw.calls == 2

def test_owned_task_handle_lane_kind_annotation_resolves_runtime_contract() -> None:
    from typing import get_type_hints

    from noetrium_platform.foundation.kernel.concurrency.runtime.task_handles import _OwnedTaskHandle

    hints = get_type_hints(_OwnedTaskHandle.lane_kind.fget)
    assert hints["return"] is ExecutionLaneKind

@pytest.mark.skipif(os.name != "nt", reason="Windows path namespace identity is platform-specific")
def test_windows_interprocess_lock_identity_is_lexical(monkeypatch, tmp_path: Path) -> None:
    guard = tmp_path / "guard.lock"
    guard.touch()
    expected = InterprocessFileLock(guard)._windows_mutex_name()

    def forbidden_resolve(self: Path, strict: bool = False) -> Path:
        del self, strict
        raise AssertionError("mutex identity must not dereference live filesystem state")

    monkeypatch.setattr(Path, "resolve", forbidden_resolve)
    assert InterprocessFileLock(guard)._windows_mutex_name() == expected

