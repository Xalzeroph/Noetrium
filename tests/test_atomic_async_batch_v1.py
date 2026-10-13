from __future__ import annotations

import asyncio
from threading import Event, Lock

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
    TaskFailurePolicy,
)
from noetrium_platform.foundation.kernel.concurrency.composition import (
    build_concurrency_runtime,
)


def _runtime():
    return build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_serial_workers=1,
            max_cpu_workers=1,
            max_blocking_io_in_flight=1,
            max_async_io_in_flight=2,
            max_cpu_in_flight=1,
            default_queue_capacity=8,
        )
    )


def test_atomic_async_batch_starts_ready_set_concurrently() -> None:
    runtime = _runtime()
    group = runtime.open_task_group(
        "atomic-async-ready-set",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    lock = Lock()
    both_started = Event()
    entered = 0

    def make_task(value: int):
        async def run(context):
            nonlocal entered
            context.checkpoint()
            with lock:
                entered += 1
                if entered == 2:
                    both_started.set()
            deadline = asyncio.get_running_loop().time() + 1.0
            while not both_started.is_set():
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError("atomic async ready set did not start together")
                await asyncio.sleep(0.001)
            context.checkpoint()
            return value
        return run

    try:
        handles = group.submit_atomic_batch(
            (
                (
                    ExecutionSpec(
                        task_id="async-left",
                        lane_kind=ExecutionLaneKind.ASYNC_IO,
                        failure_scope=TaskFailureScope.CALLER,
                    ),
                    make_task(1),
                ),
                (
                    ExecutionSpec(
                        task_id="async-right",
                        lane_kind=ExecutionLaneKind.ASYNC_IO,
                        failure_scope=TaskFailureScope.CALLER,
                    ),
                    make_task(2),
                ),
            )
        )
        assert tuple(handle.result(2.0) for handle in handles) == (1, 2)
        assert entered == 2
    finally:
        group.close(cancel_pending=True)
        runtime.close()


def test_atomic_async_batch_rejects_over_capacity_without_partial_start() -> None:
    runtime = _runtime()
    group = runtime.open_task_group(
        "atomic-async-over-capacity",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    entered: list[int] = []

    def make_task(value: int):
        async def run(context):
            entered.append(value)
            context.checkpoint()
            return value
        return run

    try:
        items = tuple(
            (
                ExecutionSpec(
                    task_id=f"async-{index}",
                    lane_kind=ExecutionLaneKind.ASYNC_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                make_task(index),
            )
            for index in range(3)
        )
        with pytest.raises(ValueError, match="exceeds provider capacity"):
            group.submit_atomic_batch(items)
        assert entered == []
    finally:
        group.close(cancel_pending=True)
        runtime.close()
