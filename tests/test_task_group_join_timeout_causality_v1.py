"""Separate child TimeoutError evidence from physical join timeout evidence."""
from __future__ import annotations

from threading import Event

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailurePolicy,
    TaskFailureScope,
)
from noetrium_platform.foundation.kernel.concurrency.composition import (
    build_concurrency_runtime,
)


def _runtime():
    return build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=3,
            max_cpu_workers=1,
            default_queue_capacity=8,
        )
    )


def test_child_timeout_exception_remains_caller_owned() -> None:
    runtime = _runtime()
    group = runtime.open_task_group(
        "caller-timeout-distinction",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )

    def fail(_context):
        raise TimeoutError("an actual provider timeout")

    handle = group.submit(
        ExecutionSpec(
            task_id="provider-failure",
            lane_kind=ExecutionLaneKind.BLOCKING_IO,
            failure_scope=TaskFailureScope.CALLER,
        ),
        fail,
    )
    with pytest.raises(TimeoutError, match="actual provider timeout"):
        handle.result()
    group.wait(timeout=1)
    group.close()
    runtime.close()


def test_child_timeout_exception_remains_group_owned() -> None:
    runtime = _runtime()
    group = runtime.open_task_group(
        "group-timeout-distinction",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )

    def fail(_context):
        raise TimeoutError("provider raised timeout")

    handle = group.submit(
        ExecutionSpec(
            task_id="provider-failure",
            lane_kind=ExecutionLaneKind.BLOCKING_IO,
            failure_scope=TaskFailureScope.GROUP,
        ),
        fail,
    )
    with pytest.raises(TimeoutError, match="provider raised timeout"):
        handle.result()
    with pytest.raises(ExceptionGroup) as raised:
        group.wait(timeout=1)
    assert len(raised.value.exceptions) == 1
    assert "provider raised timeout" in str(raised.value.exceptions[0])
    try:
        group.close()
    except ExceptionGroup:
        pass
    runtime.close()


def test_join_timeout_aggregates_pending_task_identities() -> None:
    runtime = _runtime()
    group = runtime.open_task_group("join-timeout-causality")
    release = Event()

    def block(_context):
        release.wait(timeout=5)

    for index in range(3):
        group.submit(
            ExecutionSpec(
                task_id=f"pending-{index}",
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
            ),
            block,
        )
    try:
        with pytest.raises(ExceptionGroup) as raised:
            group.wait(timeout=0.02)
        physical = [
            exc for exc in raised.value.exceptions
            if isinstance(exc, TimeoutError)
        ]
        assert len(physical) == 1
        assert set(physical[0].pending_task_ids) == {
            "pending-0", "pending-1", "pending-2",
        }
    finally:
        release.set()
        group.wait(timeout=5)
        group.close()
        runtime.close()
