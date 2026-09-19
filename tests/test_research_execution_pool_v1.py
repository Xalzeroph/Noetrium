from __future__ import annotations

from threading import Event

import pytest

from noetrium.platform import bind_research_execution_pool
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskContextPort,
)
from noetrium_platform.research.execution.admission.api import AdmissionBudget


def test_pool_group_lifecycle_unregisters_identity_for_safe_reuse() -> None:
    pool = bind_research_execution_pool()
    try:
        first = pool.open_experiment_group("study:reuse", tenant_id="project-a")
        pool.close_experiment_group(first)
        second = pool.open_experiment_group("study:reuse", tenant_id="project-a")
        pool.close_experiment_group(second)
        assert pool.experiment_admission_snapshot().groups == ()
    finally:
        pool.close()


def test_experiment_and_model_io_use_independent_admission_domains() -> None:
    pool = bind_research_execution_pool(
        experiment_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=1, max_cpu_workers=1, max_async_io_in_flight=1,
        ),
        experiment_admission_budget=AdmissionBudget(
            max_total_in_flight=1, max_in_flight_per_group=1,
            max_blocking_io_in_flight=1, max_async_io_in_flight=1,
        ),
        model_io_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=1, max_cpu_workers=1, max_async_io_in_flight=1,
        ),
        model_io_admission_budget=AdmissionBudget(
            max_total_in_flight=1, max_in_flight_per_group=1,
            max_blocking_io_in_flight=1, max_async_io_in_flight=1,
        ),
    )
    outer = pool.open_experiment_group("outer")
    model = pool.open_model_io_group("model")
    release = Event()
    entered = Event()

    def run_outer(context: TaskContextPort) -> int:
        entered.set()
        async def model_call(model_context: TaskContextPort) -> int:
            model_context.checkpoint()
            return 7
        handle = model.submit(
            ExecutionSpec(task_id="model-call", lane_kind=ExecutionLaneKind.ASYNC_IO),
            model_call,
        )
        value = handle.result(1)
        release.wait(1)
        context.checkpoint()
        return value

    try:
        handle = outer.submit(
            ExecutionSpec(task_id="outer-call", lane_kind=ExecutionLaneKind.BLOCKING_IO),
            run_outer,
        )
        assert entered.wait(1)
        release.set()
        assert handle.result(1) == 7
    finally:
        pool.close_experiment_group(outer)
        pool.close_model_io_group(model)
        pool.close()


def test_pool_shares_exact_model_admission_by_deployment_generation() -> None:
    pool = bind_research_execution_pool()
    generation = "a" * 64
    try:
        first = pool.model_admission.controller_for(
            deployment_id="qwen", deployment_generation=generation, qualified_capacity=2,
        )
        second = pool.model_admission.controller_for(
            deployment_id="qwen", deployment_generation=generation, qualified_capacity=2,
        )
        assert first is second
        lease_a = first.acquire(timeout_seconds=0.1)
        lease_b = second.acquire(timeout_seconds=0.1)
        with pytest.raises(TimeoutError):
            first.acquire(timeout_seconds=0.01)
        lease_b.release()
        lease_a.release()
    finally:
        pool.close()


def test_orchestration_experiment_model_dependency_chain_has_no_nested_admission_deadlock() -> None:
    one = ConcurrencyBudget(
        max_blocking_io_workers=1,
        max_cpu_workers=1,
        max_async_io_in_flight=1,
    )
    one_admission = AdmissionBudget(
        max_total_in_flight=1,
        max_in_flight_per_group=1,
        max_blocking_io_in_flight=1,
        max_async_io_in_flight=1,
    )
    pool = bind_research_execution_pool(
        orchestration_concurrency_budget=one,
        orchestration_admission_budget=one_admission,
        experiment_concurrency_budget=one,
        experiment_admission_budget=one_admission,
        model_io_concurrency_budget=one,
        model_io_admission_budget=one_admission,
    )
    orchestration = pool.open_orchestration_group("campaign")
    experiment = pool.open_experiment_group("study")
    model = pool.open_model_io_group("model")

    async def model_call(context: TaskContextPort) -> int:
        context.checkpoint()
        return 17

    def study_call(context: TaskContextPort) -> int:
        context.checkpoint()
        handle = model.submit(
            ExecutionSpec(task_id="nested-model", lane_kind=ExecutionLaneKind.ASYNC_IO),
            model_call,
        )
        return handle.result(1)

    def campaign_call(context: TaskContextPort) -> int:
        context.checkpoint()
        handle = experiment.submit(
            ExecutionSpec(task_id="nested-study", lane_kind=ExecutionLaneKind.BLOCKING_IO),
            study_call,
        )
        return handle.result(1)

    try:
        handle = orchestration.submit(
            ExecutionSpec(task_id="nested-campaign", lane_kind=ExecutionLaneKind.BLOCKING_IO),
            campaign_call,
        )
        assert handle.result(2) == 17
    finally:
        pool.close_orchestration_group(orchestration)
        pool.close_experiment_group(experiment)
        pool.close_model_io_group(model)
        pool.close()

