from __future__ import annotations

from threading import Barrier, Lock

import pytest

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
)
from noetrium_platform.research.execution.policy.api import AdmissionBudget


def _pool() -> ResearchExecutionPool:
    return ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_blocking_io_in_flight=1,
            max_cpu_workers=1,
            max_cpu_in_flight=1,
            max_async_io_in_flight=1,
        ),
        orchestration_admission_budget=AdmissionBudget(max_total_in_flight=1),
        experiment_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_blocking_io_in_flight=4,
            max_cpu_workers=1,
            max_cpu_in_flight=1,
            max_async_io_in_flight=2,
        ),
        experiment_admission_budget=AdmissionBudget(
            max_total_in_flight=4,
            max_in_flight_per_group=4,
            max_in_flight_per_tenant=4,
            max_in_flight_per_resource=4,
            max_blocking_io_in_flight=4,
            max_async_io_in_flight=2,
            max_cpu_in_flight=1,
            max_serial_in_flight=1,
        ),
        model_io_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_blocking_io_in_flight=1,
            max_cpu_workers=1,
            max_cpu_in_flight=1,
            max_async_io_in_flight=1,
        ),
        model_io_admission_budget=AdmissionBudget(max_total_in_flight=1),
    )


def _spec(task_id: str) -> ExecutionSpec:
    return ExecutionSpec(
        task_id=task_id,
        lane_kind=ExecutionLaneKind.BLOCKING_IO,
        failure_scope=TaskFailureScope.CALLER,
    )


def test_atomic_batch_enters_two_blocking_workers_concurrently() -> None:
    pool = _pool()
    group = pool.open_experiment_group("atomic-success")
    gate = Barrier(2)
    entered: list[str] = []
    lock = Lock()

    def task(name: str):
        def run(context):
            context.checkpoint()
            with lock:
                entered.append(name)
            gate.wait(timeout=2.0)
            context.checkpoint()
            return name
        return run

    try:
        handles = group.submit_atomic_batch(
            (
                (_spec("a"), task("a")),
                (_spec("b"), task("b")),
            )
        )
        assert tuple(handle.result(timeout=2.0) for handle in handles) == ("a", "b")
        assert sorted(entered) == ["a", "b"]
    finally:
        pool.close_experiment_group(group)
        pool.close()


def test_atomic_batch_never_starts_partial_ready_set_when_workers_are_insufficient() -> None:
    pool = _pool()
    group = pool.open_experiment_group("atomic-over-capacity")
    entered: list[str] = []
    lock = Lock()

    def task(name: str):
        def run(context):
            with lock:
                entered.append(name)
            context.checkpoint()
            return name
        return run

    try:
        with pytest.raises(
            ValueError,
            match="physical worker parallelism",
        ):
            group.submit_atomic_batch(
                (
                    (_spec("a"), task("a")),
                    (_spec("b"), task("b")),
                    (_spec("c"), task("c")),
                )
            )
        assert entered == []
        assert pool.experiment_admission_snapshot().in_flight == 0
    finally:
        pool.close_experiment_group(group)
        pool.close()
