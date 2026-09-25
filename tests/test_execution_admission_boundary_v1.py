from __future__ import annotations

from threading import Event

import pytest

from noetrium_platform.composition.concurrency import (
    build_execution_concurrency_runtime,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ExecutionLaneKind,
    ExecutionPermitRejected,
    ExecutionSpec,
    TaskFailureScope,
)
from noetrium_platform.research.execution.policy.api import (
    AdmissionBudget,
    AdmissionMode,
)


def _budget(*, blocking_in_flight: int = 1) -> ConcurrencyBudget:
    return ConcurrencyBudget(
        max_blocking_io_workers=1,
        max_blocking_io_in_flight=blocking_in_flight,
        max_async_io_in_flight=1,
        max_cpu_workers=1,
        max_cpu_in_flight=1,
        max_serial_workers=1,
    )


def _admission(*, total: int = 1, blocking: int = 1) -> AdmissionBudget:
    return AdmissionBudget(
        max_total_in_flight=total,
        max_in_flight_per_group=total,
        max_in_flight_per_tenant=total,
        max_in_flight_per_resource=total,
        max_blocking_io_in_flight=blocking,
        max_async_io_in_flight=1,
        max_cpu_in_flight=1,
        max_serial_in_flight=1,
    )


def test_rejected_submission_leaves_no_task_residue() -> None:
    runtime = build_execution_concurrency_runtime(
        concurrency_budget=_budget(),
        admission_budget=_admission(),
    )
    blocker = runtime.open_task_group("blocker")
    rejected = runtime.open_task_group(
        "rejected",
        admission_mode=AdmissionMode.REJECT,
    )
    entered = Event()
    release = Event()

    def hold(context) -> str:
        context.checkpoint()
        entered.set()
        if not release.wait(2.0):
            raise TimeoutError("fixture release was not signalled")
        context.checkpoint()
        return "done"

    handle = blocker.submit(
        ExecutionSpec(
            task_id="hold",
            lane_kind=ExecutionLaneKind.BLOCKING_IO,
            failure_scope=TaskFailureScope.CALLER,
        ),
        hold,
    )
    assert entered.wait(2.0)

    try:
        with pytest.raises(ExecutionPermitRejected):
            rejected.submit(
                ExecutionSpec(
                    task_id="never-accepted",
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                lambda context: "unexpected",
            )
        assert rejected.snapshot().tasks == ()
        assert runtime.admission_snapshot().in_flight == 1
    finally:
        release.set()
        assert handle.result(2.0) == "done"
        runtime.close_task_group(rejected)
        runtime.close_task_group(blocker)
        runtime.close()


def test_execution_runtime_rejects_admission_overbooking_provider() -> None:
    with pytest.raises(
        ValueError,
        match="admission cannot exceed provider in-flight capacity",
    ):
        build_execution_concurrency_runtime(
            concurrency_budget=_budget(blocking_in_flight=1),
            admission_budget=_admission(total=2, blocking=2),
        )
