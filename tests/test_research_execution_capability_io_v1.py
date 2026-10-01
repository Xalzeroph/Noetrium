from __future__ import annotations

from threading import Event

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget, ExecutionLaneKind, ExecutionSpec, TaskContextPort,
)


def test_experiment_waiting_on_capability_io_does_not_self_deadlock() -> None:
    one = ConcurrencyBudget(max_blocking_io_workers=1, max_cpu_workers=1, max_async_io_in_flight=1)
    two_io = ConcurrencyBudget(max_blocking_io_workers=2, max_cpu_workers=1, max_async_io_in_flight=1)
    pool = ResearchExecutionPool(
        orchestration_concurrency_budget=one,
        experiment_concurrency_budget=one,
        capability_io_concurrency_budget=two_io,
        model_io_concurrency_budget=one,
    )
    experiment = pool.open_experiment_group("experiment")
    capability = pool.open_capability_io_group("capability")
    release = Event()

    def drain(context: TaskContextPort) -> int:
        context.checkpoint()
        assert release.wait(1.0)
        return 1

    def trial(context: TaskContextPort) -> int:
        context.checkpoint()
        handles = capability.submit_atomic_batch((
            (ExecutionSpec(task_id="stdout", lane_kind=ExecutionLaneKind.BLOCKING_IO), drain),
            (ExecutionSpec(task_id="stderr", lane_kind=ExecutionLaneKind.BLOCKING_IO), drain),
        ))
        release.set()
        return sum(handle.result(1.0) for handle in handles)

    try:
        handle = experiment.submit(
            ExecutionSpec(task_id="trial", lane_kind=ExecutionLaneKind.BLOCKING_IO),
            trial,
        )
        assert handle.result(2.0) == 2
    finally:
        pool.close_experiment_group(experiment)
        pool.close_capability_io_group(capability)
        pool.close()
