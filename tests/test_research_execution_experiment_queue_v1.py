from __future__ import annotations

from threading import Event

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskContextPort,
)


def test_default_experiment_domain_queues_beyond_worker_count() -> None:
    pool = ResearchExecutionPool()
    group = pool.open_experiment_group("queued-experiment")
    release = Event()

    def hold(context: TaskContextPort, value: int) -> int:
        context.checkpoint()
        assert release.wait(2.0)
        context.checkpoint()
        return value

    try:
        handles = tuple(
            group.submit(
                ExecutionSpec(
                    task_id=f"assignment-{index}",
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                ),
                hold,
                index,
                deadline=Deadline.after(1.0),
            )
            for index in range(9)
        )
        release.set()
        assert tuple(handle.result(1.0) for handle in handles) == tuple(range(9))
    finally:
        release.set()
        pool.close_experiment_group(group, cancel_pending=True)
        pool.close()
