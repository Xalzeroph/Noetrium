"""A terminal provider TimeoutError must not become a logical task deadline."""
from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget, Deadline, ExecutionLaneKind, ExecutionSpec,
    TaskDeadlineExceeded, TaskFailurePolicy, TaskFailureScope,
)
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime


@pytest.mark.parametrize("lane", (ExecutionLaneKind.BLOCKING_IO, ExecutionLaneKind.ASYNC_IO))
def test_child_timeout_under_live_task_deadline_preserves_child_failure(lane) -> None:
    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            default_queue_capacity=4,
        )
    )
    group = runtime.open_task_group(
        "provider-timeout-under-deadline-" + str(lane),
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )

    def fail_sync(_ctx):
        raise TimeoutError("provider-side transport timeout")

    async def fail_async(_ctx):
        raise TimeoutError("provider-side transport timeout")

    try:
        handle = group.submit(
            ExecutionSpec(
                task_id="provider-task",
                lane_kind=lane,
                failure_scope=TaskFailureScope.CALLER,
            ),
            fail_async if lane is ExecutionLaneKind.ASYNC_IO else fail_sync,
            deadline=Deadline.after(4),
        )
        # The task deadline, not this caller timeout, bounds the wait.
        with pytest.raises(TimeoutError, match="provider-side transport") as raised:
            handle.result(timeout=8)
        assert type(raised.value) is TimeoutError
        assert not isinstance(raised.value, TaskDeadlineExceeded)
        group.wait(timeout=2)
        group.close()
    finally:
        runtime.close()
