from __future__ import annotations

import asyncio
from threading import Event

from noetrium_platform.foundation.kernel.concurrency.providers.async_io import AsyncIoExecutor
from noetrium_platform.foundation.kernel.concurrency.providers.executors import BoundedThreadExecutor


def test_bounded_thread_try_submit_never_waits_for_capacity() -> None:
    hold = Event()
    executor = BoundedThreadExecutor(max_workers=1, max_in_flight=1)
    running = executor.submit(lambda: hold.wait(5))
    try:
        assert executor.try_submit(lambda: None) is None
    finally:
        hold.set()
        running.result(2)
        executor.close()


def test_async_io_try_submit_never_waits_for_capacity() -> None:
    executor = AsyncIoExecutor(max_in_flight=1)
    hold = asyncio.Event()

    async def first() -> None:
        await hold.wait()

    running = executor.submit(first)
    try:
        assert executor.try_submit(lambda: asyncio.sleep(0)) is None
    finally:
        loop = executor._loop
        assert loop is not None
        loop.call_soon_threadsafe(hold.set)
        running.result(2)
        executor.close()


def test_task_result_exposes_capacity_only_after_release() -> None:
    from threading import Barrier, Event

    from resource_test_support import make_execution_pool
    from noetrium_platform.composition.shared_host_pressure import (
        ResourceCompetitionDemand,
    )
    from noetrium_platform.foundation.kernel.concurrency.api import (
        ConcurrencyBudget,
        ExecutionLaneKind,
        ExecutionSpec,
        TaskFailureScope,
    )
    from noetrium_platform.research.execution.policy.api import AdmissionBudget

    pool = make_execution_pool(
        experiment_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=3,
            max_blocking_io_in_flight=3,
            max_cpu_workers=1,
            max_cpu_in_flight=1,
            max_async_io_in_flight=1,
        ),
        experiment_admission_budget=AdmissionBudget(
            max_total_in_flight=3,
            max_in_flight_per_group=3,
            max_in_flight_per_tenant=3,
            max_in_flight_per_resource=3,
            max_blocking_io_in_flight=3,
            max_async_io_in_flight=1,
            max_cpu_in_flight=1,
            max_serial_in_flight=1,
        ),
    )
    demand = ResourceCompetitionDemand(
        memory_bytes_per_permit=1024,
        pids_per_permit=1,
        fds_per_permit=2,
    )
    group = pool.open_experiment_group(
        "completion-release-fence",
        resource_demand=demand,
    )
    barrier = Barrier(4)
    release = Event()

    def spec(index: int) -> ExecutionSpec:
        return ExecutionSpec(
            task_id=f"fenced-{index}",
            lane_kind=ExecutionLaneKind.BLOCKING_IO,
            failure_scope=TaskFailureScope.CALLER,
        )

    def task(index: int):
        def run(context):
            context.checkpoint()
            barrier.wait(timeout=2)
            release.wait(5)
            context.checkpoint()
            return index

        return run

    try:
        handles = group.try_submit_atomic_batch(
            tuple((spec(index), task(index)) for index in range(3))
        )
        assert handles is not None
        barrier.wait(timeout=2)
        assert (
            pool._resource_competition_reservations.reserved_demand()
            == ResourceCompetitionDemand(
                memory_bytes_per_permit=3072,
                pids_per_permit=3,
                fds_per_permit=6,
            )
        )

        release.set()
        assert tuple(handle.result(2) for handle in handles) == (0, 1, 2)
        assert (
            pool._resource_competition_reservations.reserved_demand()
            == ResourceCompetitionDemand()
        )

        replacement = group.try_submit(spec(99), lambda context: 99)
        assert replacement is not None
        assert replacement.result(2) == 99
        assert (
            pool._resource_competition_reservations.reserved_demand()
            == ResourceCompetitionDemand()
        )
    finally:
        release.set()
        pool.close_experiment_group(group)
        pool.close()


def test_nonblocking_atomic_batch_never_enters_executor_private_queue() -> None:
    from threading import Barrier, Event, Lock

    from resource_test_support import make_execution_pool
    from noetrium_platform.foundation.kernel.concurrency.api import (
        ConcurrencyBudget,
        ExecutionLaneKind,
        ExecutionSpec,
        TaskFailureScope,
    )
    from noetrium_platform.research.execution.policy.api import AdmissionBudget

    pool = make_execution_pool(
        experiment_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_blocking_io_in_flight=4,
            max_cpu_workers=1,
            max_cpu_in_flight=1,
            max_async_io_in_flight=1,
        ),
        experiment_admission_budget=AdmissionBudget(
            max_total_in_flight=4,
            max_in_flight_per_group=4,
            max_in_flight_per_tenant=4,
            max_in_flight_per_resource=4,
            max_blocking_io_in_flight=4,
            max_async_io_in_flight=1,
            max_cpu_in_flight=1,
            max_serial_in_flight=1,
        ),
    )
    group = pool.open_experiment_group("no-hidden-executor-queue")
    hold = Event()
    holder_entered = Event()
    entered: list[str] = []
    lock = Lock()

    def spec(task_id: str) -> ExecutionSpec:
        return ExecutionSpec(
            task_id=task_id,
            lane_kind=ExecutionLaneKind.BLOCKING_IO,
            failure_scope=TaskFailureScope.CALLER,
        )

    def holder(context):
        holder_entered.set()
        hold.wait(5)
        return "holder"

    def task(name: str, barrier: Barrier | None = None):
        def run(context):
            with lock:
                entered.append(name)
            if barrier is not None:
                barrier.wait(timeout=2)
            return name

        return run

    try:
        held = group.submit(spec("holder"), holder)
        assert holder_entered.wait(2)

        assert (
            group.try_submit_atomic_batch(
                (
                    (spec("a"), task("a")),
                    (spec("b"), task("b")),
                )
            )
            is None
        )
        assert entered == []
        snapshot = pool.experiment_admission_snapshot()
        assert snapshot.in_flight == 1
        assert snapshot.waiting == 0

        hold.set()
        assert held.result(2) == "holder"

        simultaneous = Barrier(2)
        handles = group.try_submit_atomic_batch(
            (
                (spec("c"), task("c", simultaneous)),
                (spec("d"), task("d", simultaneous)),
            )
        )
        assert handles is not None
        assert tuple(handle.result(2) for handle in handles) == ("c", "d")
        assert sorted(entered) == ["c", "d"]
    finally:
        hold.set()
        pool.close_experiment_group(group)
        pool.close()
