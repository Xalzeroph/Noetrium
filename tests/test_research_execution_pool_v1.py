from __future__ import annotations

from threading import Event

import pytest

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.shared_host_pressure import (
    ResourceCompetitionDemand,
    ResourceCompetitionPolicy,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskContextPort,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    HostRuntimeSnapshot,
    HostRuntimeStatus,
)
from noetrium_platform.research.execution.policy.api import (
    AdmissionBudget,
    AdmissionMode,
    AdmissionRejected,
)


def _cpu_identity(value: int) -> int:
    return value


class _FixedHostObserver:
    def snapshot(self) -> HostRuntimeSnapshot:
        return HostRuntimeSnapshot(
            True,
            (
                HostRuntimeStatus(
                    "shared-node",
                    True,
                    effective_cpu_cores=8.0,
                    cpu_load_1m=0.0,
                    available_memory_bytes=2 * 1024**3,
                    cpu_pressure_some_avg10_percent=0.0,
                    memory_pressure_some_avg10_percent=0.0,
                    io_pressure_some_avg10_percent=0.0,
                    available_pids=1024,
                    available_fds=4096,
                ),
            ),
        )


def test_pool_group_lifecycle_unregisters_identity_for_safe_reuse() -> None:
    pool = ResearchExecutionPool()
    try:
        first = pool.open_experiment_group("study:reuse", tenant_id="project-a")
        pool.close_experiment_group(first)
        second = pool.open_experiment_group("study:reuse", tenant_id="project-a")
        pool.close_experiment_group(second)
        assert pool.experiment_admission_snapshot().groups == ()
    finally:
        pool.close()


def test_experiment_and_model_io_use_independent_admission_domains() -> None:
    pool = ResearchExecutionPool(
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


def test_workload_domains_share_one_physical_resource_reservation_ledger() -> None:
    pool = ResearchExecutionPool(
        host_runtime_observer=_FixedHostObserver(),
        resource_competition_policy=ResourceCompetitionPolicy(
            min_available_memory_bytes=1024**3,
            min_available_pids=0,
            min_available_fds=0,
            min_storage_free_bytes=0,
            min_storage_free_inodes=0,
        ),
    )
    demand = ResourceCompetitionDemand(
        memory_bytes_per_permit=1024**3,
    )
    orchestration = pool.open_orchestration_group(
        "reserve-orchestration",
        admission_mode=AdmissionMode.REJECT,
        resource_demand=demand,
    )
    experiment = pool.open_experiment_group(
        "reserve-experiment",
        admission_mode=AdmissionMode.REJECT,
        resource_demand=demand,
    )
    entered = Event()
    release = Event()

    def hold(context: TaskContextPort) -> None:
        context.checkpoint()
        entered.set()
        if not release.wait(2):
            raise TimeoutError("reservation test release was not signalled")
        context.checkpoint()

    def quick(context: TaskContextPort) -> int:
        context.checkpoint()
        return 1

    try:
        first = orchestration.submit(
            ExecutionSpec(
                task_id="hold-reservation",
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
            ),
            hold,
        )
        assert entered.wait(1)

        # The experiment admission domain has independent logical admission
        # capacity, but it must see the orchestration domain's physical-memory
        # reservation before the first task appears in host runtime facts.
        with pytest.raises(AdmissionRejected, match="memory-headroom"):
            experiment.submit(
                ExecutionSpec(
                    task_id="cross-domain-overbook",
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                ),
                quick,
            )

        release.set()
        first.result(1)
        second = experiment.submit(
            ExecutionSpec(
                task_id="after-reservation-release",
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
            ),
            quick,
        )
        assert second.result(1) == 1
    finally:
        release.set()
        pool.close_orchestration_group(
            orchestration,
            cancel_pending=True,
        )
        pool.close_experiment_group(
            experiment,
            cancel_pending=True,
        )
        pool.close()


def test_pool_shares_exact_model_admission_by_deployment_generation() -> None:
    pool = ResearchExecutionPool()
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
    pool = ResearchExecutionPool(
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



def test_workload_quiesce_seals_work_domains_but_keeps_cleanup_orchestration_alive() -> None:
    pool = ResearchExecutionPool()
    pool.quiesce_workloads()

    for operation in (
        lambda: pool.open_experiment_group("late-experiment"),
        lambda: pool.open_model_io_group("late-model-io"),
        lambda: pool.compute_lease_guard_factory(object()),
        lambda: pool.endpoint_lease_guard_factory(object()),
        lambda: pool.environment_instance_lease_guard_factory(object()),
        lambda: pool.docker_container_lease_guard_factory(object()),
    ):
        with pytest.raises(RuntimeError, match="workloads are quiesced"):
            operation()

    cleanup = pool.open_orchestration_group("terminal-cleanup")
    pool.close_orchestration_group(cleanup)
    pool.close()


def test_workload_failure_does_not_block_physical_quiescence_or_pool_close() -> None:
    pool = ResearchExecutionPool()
    group = pool.open_experiment_group("failed-workload")

    def boom(context: TaskContextPort) -> None:
        context.checkpoint()
        raise RuntimeError("simulated workload failure")

    handle = group.submit(
        ExecutionSpec(task_id="boom", lane_kind=ExecutionLaneKind.BLOCKING_IO),
        boom,
    )
    with pytest.raises(RuntimeError, match="simulated workload failure"):
        handle.result(1)

    # The logical workload failure remains observable on the child handle, but
    # terminal resource teardown depends on physical convergence, not success.
    pool.quiesce_workloads()
    with pytest.raises(RuntimeError, match="workloads are quiescing"):
        pool.open_experiment_group("late")
    pool.close()


def test_control_plane_runs_while_orchestration_capacity_is_saturated() -> None:
    one = ConcurrencyBudget(
        max_blocking_io_workers=1,
        max_blocking_io_in_flight=1,
        max_async_io_in_flight=1,
        max_cpu_workers=1,
        max_cpu_in_flight=1,
        max_serial_workers=1,
    )
    one_admission = AdmissionBudget(
        max_total_in_flight=1,
        max_in_flight_per_group=1,
        max_in_flight_per_tenant=1,
        max_in_flight_per_resource=1,
        max_blocking_io_in_flight=1,
        max_async_io_in_flight=1,
        max_cpu_in_flight=1,
        max_serial_in_flight=1,
    )
    pool = ResearchExecutionPool(
        orchestration_concurrency_budget=one,
        orchestration_admission_budget=one_admission,
        control_concurrency_budget=one,
        control_admission_budget=one_admission,
    )
    workload = pool.open_orchestration_group("saturated-orchestration")
    control = pool.open_control_group("lease-maintenance")
    workload_entered = Event()
    release_workload = Event()
    control_ran = Event()

    def hold_workload(context: TaskContextPort) -> None:
        context.checkpoint()
        workload_entered.set()
        if not release_workload.wait(2):
            raise TimeoutError("test workload release was not signalled")
        context.checkpoint()

    def run_control(context: TaskContextPort) -> None:
        context.checkpoint()
        control_ran.set()
        context.checkpoint()

    try:
        workload_handle = workload.submit(
            ExecutionSpec(
                task_id="hold-workload",
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
            ),
            hold_workload,
        )
        assert workload_entered.wait(1)
        assert pool.orchestration_admission_snapshot().in_flight == 1

        control_handle = control.submit(
            ExecutionSpec(
                task_id="renew-lease",
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
            ),
            run_control,
        )
        assert control_ran.wait(1)
        control_handle.result(1)
        assert pool.control_admission_snapshot().in_flight == 0
        assert pool.orchestration_admission_snapshot().in_flight == 1

        release_workload.set()
        workload_handle.result(1)
    finally:
        release_workload.set()
        pool.close_control_group(control, cancel_pending=True)
        pool.close_orchestration_group(workload, cancel_pending=True)
        pool.close()


def test_workload_quiesce_keeps_owned_control_group_operational() -> None:
    pool = ResearchExecutionPool()
    control = pool.open_control_group("owned-resource-heartbeats")
    ran = Event()
    try:
        pool.quiesce_workloads()

        def maintenance(context: TaskContextPort) -> None:
            context.checkpoint()
            ran.set()
            context.checkpoint()

        handle = control.submit(
            ExecutionSpec(
                task_id="post-quiesce-maintenance",
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
            ),
            maintenance,
        )
        assert ran.wait(1)
        handle.result(1)
    finally:
        pool.close_control_group(control, cancel_pending=True)
        pool.close()


def test_workload_domains_share_one_cpu_provider_while_control_is_isolated() -> None:
    budget = ConcurrencyBudget(
        max_blocking_io_workers=1,
        max_serial_workers=1,
        max_cpu_workers=2,
        max_blocking_io_in_flight=1,
        max_async_io_in_flight=1,
        max_cpu_in_flight=2,
        default_queue_capacity=8,
    )
    pool = ResearchExecutionPool(
        orchestration_concurrency_budget=budget,
        experiment_concurrency_budget=budget,
        model_io_concurrency_budget=budget,
    )
    orchestration = pool.open_orchestration_group("shared-cpu-orchestration")
    experiment = pool.open_experiment_group("shared-cpu-experiment")
    model_io = pool.open_model_io_group("shared-cpu-model")
    try:
        shared = pool._shared_workload_cpu
        assert shared is not None
        assert pool._orchestration.concurrency._cpu is shared
        assert pool._experiments.concurrency._cpu is shared
        assert pool._model_io.concurrency._cpu is shared
        assert pool._control.concurrency._cpu is not shared
        assert pool.workload_cpu_workers == 2

        handles = (
            orchestration.submit(
                ExecutionSpec(
                    task_id="cpu-orchestration",
                    lane_kind=ExecutionLaneKind.CPU,
                ),
                _cpu_identity,
                11,
            ),
            experiment.submit(
                ExecutionSpec(
                    task_id="cpu-experiment",
                    lane_kind=ExecutionLaneKind.CPU,
                ),
                _cpu_identity,
                22,
            ),
            model_io.submit(
                ExecutionSpec(
                    task_id="cpu-model",
                    lane_kind=ExecutionLaneKind.CPU,
                ),
                _cpu_identity,
                33,
            ),
        )
        assert tuple(handle.result(10) for handle in handles) == (11, 22, 33)
    finally:
        pool.close_orchestration_group(orchestration, cancel_pending=True)
        pool.close_experiment_group(experiment, cancel_pending=True)
        pool.close_model_io_group(model_io, cancel_pending=True)
        pool.close()
    assert pool._shared_workload_cpu_closed


def test_workload_quiesce_does_not_close_cpu_provider_needed_by_orchestration() -> None:
    budget = ConcurrencyBudget(
        max_blocking_io_workers=1,
        max_serial_workers=1,
        max_cpu_workers=1,
        max_blocking_io_in_flight=1,
        max_async_io_in_flight=1,
        max_cpu_in_flight=1,
        default_queue_capacity=8,
    )
    pool = ResearchExecutionPool(
        orchestration_concurrency_budget=budget,
        experiment_concurrency_budget=budget,
        model_io_concurrency_budget=budget,
    )
    orchestration = pool.open_orchestration_group("post-quiesce-cpu")
    try:
        pool.quiesce_workloads()
        assert not pool._shared_workload_cpu_closed
        handle = orchestration.submit(
            ExecutionSpec(
                task_id="cleanup-cpu",
                lane_kind=ExecutionLaneKind.CPU,
            ),
            _cpu_identity,
            41,
        )
        assert handle.result(10) == 41
    finally:
        pool.close_orchestration_group(orchestration, cancel_pending=True)
        pool.close()
    assert pool._shared_workload_cpu_closed


def test_invalid_owner_generation_mode_fails_before_provider_construction() -> None:
    with pytest.raises(TypeError, match="exclusive_owner_generation"):
        ResearchExecutionPool(exclusive_owner_generation=1)  # type: ignore[arg-type]
