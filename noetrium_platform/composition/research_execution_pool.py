from __future__ import annotations

from uuid import uuid4

from noetrium_platform.capabilities.model.serving.api import ModelAdmissionRegistryPort
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionRegistry
from noetrium_platform.infrastructure.resources.container.api import (
    DEFAULT_DOCKER_CONTAINER_LEASE_POLICY,
    DockerContainerLeasePolicy,
)
from noetrium_platform.infrastructure.resources.container.runtime import (
    DockerContainerLeaseAuthority,
    DockerContainerLeaseHeartbeatFactory,
)
from noetrium_platform.composition.environment_instance_leases import (
    DEFAULT_ENVIRONMENT_INSTANCE_LEASE_POLICY,
    EnvironmentInstanceLeaseAuthority,
    EnvironmentInstanceLeaseHeartbeatFactory,
    EnvironmentInstanceLeasePolicy,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeLeaseGuardFactoryPort,
    ComputeLeasePolicy,
    ComputeSchedulerPort,
    DEFAULT_COMPUTE_LEASE_POLICY,
    HostRuntimeObserverPort,
)
from noetrium_platform.infrastructure.resources.compute.runtime import ComputeLeaseHeartbeatFactory
from noetrium_platform.infrastructure.resources.allocation.api import (
    DEFAULT_ENDPOINT_LEASE_POLICY,
    EndpointAllocationPort,
    EndpointLeaseGuardFactoryPort,
    EndpointLeasePolicy,
)
from noetrium_platform.infrastructure.resources.allocation.runtime import (
    EndpointLeaseHeartbeatFactory,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    Deadline,
    TaskFailurePolicy,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.concurrency.composition import (
    build_cpu_worker_pool_provider,
)
from noetrium_platform.research.execution.policy.api import AdmissionBudget, AdmissionMode
from noetrium_platform.research.execution.policy.api import ExecutionPriority

from .concurrency import build_execution_concurrency_runtime
from .shared_host_pressure import (
    ResourceCompetitionPolicy,
    SharedNetworkPressureObserverPort,
    SharedStoragePressureObserverPort,
)


def _default_control_concurrency_budget() -> ConcurrencyBudget:
    """Keep lifecycle/recovery control isolated with a minimal CPU reserve."""

    return ConcurrencyBudget(
        max_blocking_io_workers=2,
        max_serial_workers=2,
        max_cpu_workers=1,
        max_blocking_io_in_flight=8,
        max_async_io_in_flight=16,
        max_cpu_in_flight=1,
        default_queue_capacity=256,
    )


def _shared_workload_cpu_budget(
    budgets: tuple[ConcurrencyBudget, ...],
) -> ConcurrencyBudget:
    if not budgets:
        raise ValueError("shared workload CPU budget requires logical domains")
    return ConcurrencyBudget(
        max_cpu_workers=max(item.max_cpu_workers for item in budgets),
        max_cpu_in_flight=max(int(item.max_cpu_in_flight) for item in budgets),
    )


class ResearchExecutionPool:
    """Shared execution authorities for nested concurrent research workloads.

    The dependency order is explicit:

        orchestration -> experiment execution -> model I/O

    A synchronous parent may wait only on work in a downstream domain. Keeping
    the three admission/concurrency domains independent prevents nested-admission
    deadlock while preserving one composition owner and bounded resources.
    Exact model-serving capacity is shared separately through one admission
    registry per deployment generation.
    """

    def __init__(
        self,
        *,
        orchestration_concurrency_budget: ConcurrencyBudget | None = None,
        orchestration_admission_budget: AdmissionBudget | None = None,
        control_concurrency_budget: ConcurrencyBudget | None = None,
        control_admission_budget: AdmissionBudget | None = None,
        experiment_concurrency_budget: ConcurrencyBudget | None = None,
        experiment_admission_budget: AdmissionBudget | None = None,
        model_io_concurrency_budget: ConcurrencyBudget | None = None,
        model_io_admission_budget: AdmissionBudget | None = None,
        priority_aging_seconds: float = 1.0,
        host_runtime_observer: HostRuntimeObserverPort | None = None,
        storage_pressure_observer: SharedStoragePressureObserverPort | None = None,
        network_pressure_observer: SharedNetworkPressureObserverPort | None = None,
        resource_competition_policy: ResourceCompetitionPolicy | None = None,
        exclusive_owner_generation: bool = False,
    ) -> None:
        if type(exclusive_owner_generation) is not bool:
            raise TypeError("exclusive_owner_generation must be boolean")

        resolved_control_budget = (
            control_concurrency_budget or _default_control_concurrency_budget()
        )
        resolved_orchestration_budget = (
            orchestration_concurrency_budget or ConcurrencyBudget()
        )
        resolved_experiment_budget = (
            experiment_concurrency_budget or ConcurrencyBudget()
        )
        resolved_model_io_budget = (
            model_io_concurrency_budget or ConcurrencyBudget()
        )
        shared_cpu_budget = _shared_workload_cpu_budget(
            (
                resolved_orchestration_budget,
                resolved_experiment_budget,
                resolved_model_io_budget,
            )
        )

        self._control = build_execution_concurrency_runtime(
            concurrency_budget=resolved_control_budget,
            admission_budget=control_admission_budget,
            priority_aging_seconds=priority_aging_seconds,
            blocking_io_thread_name_prefix="research-control-io",
            timer_name="research-control-timer",
        )
        self._shared_workload_cpu = None
        self._shared_workload_cpu_closed = False
        try:
            self._shared_workload_cpu = build_cpu_worker_pool_provider(
                shared_cpu_budget
            )
            self._orchestration = build_execution_concurrency_runtime(
                concurrency_budget=resolved_orchestration_budget,
                admission_budget=orchestration_admission_budget,
                priority_aging_seconds=priority_aging_seconds,
                host_runtime_observer=host_runtime_observer,
                storage_pressure_observer=storage_pressure_observer,
                network_pressure_observer=network_pressure_observer,
                resource_competition_policy=resource_competition_policy,
                blocking_io_thread_name_prefix="research-orchestration-io",
                timer_name="research-orchestration-timer",
                cpu_provider=self._shared_workload_cpu,
            )
            self._experiments = build_execution_concurrency_runtime(
                concurrency_budget=resolved_experiment_budget,
                admission_budget=experiment_admission_budget,
                priority_aging_seconds=priority_aging_seconds,
                host_runtime_observer=host_runtime_observer,
                storage_pressure_observer=storage_pressure_observer,
                network_pressure_observer=network_pressure_observer,
                resource_competition_policy=resource_competition_policy,
                blocking_io_thread_name_prefix="research-experiment-io",
                timer_name="research-experiment-timer",
                cpu_provider=self._shared_workload_cpu,
            )
            self._model_io = build_execution_concurrency_runtime(
                concurrency_budget=resolved_model_io_budget,
                admission_budget=model_io_admission_budget,
                priority_aging_seconds=priority_aging_seconds,
                host_runtime_observer=host_runtime_observer,
                resource_competition_policy=resource_competition_policy,
                blocking_io_thread_name_prefix="research-model-io",
                timer_name="research-model-timer",
                cpu_provider=self._shared_workload_cpu,
            )
            self._model_admission: ModelAdmissionRegistryPort = ModelAdmissionRegistry()
        except BaseException as exc:
            errors: list[BaseException] = [exc]
            for name in ("_model_io", "_experiments", "_orchestration"):
                runtime = getattr(self, name, None)
                if runtime is None:
                    continue
                try:
                    runtime.close()
                except BaseException as cleanup_exc:
                    errors.append(cleanup_exc)
            if self._shared_workload_cpu is not None:
                try:
                    self._shared_workload_cpu.close(
                        wait=True,
                        cancel_pending=True,
                    )
                except BaseException as cleanup_exc:
                    errors.append(cleanup_exc)
            try:
                self._control.close()
            except BaseException as cleanup_exc:
                errors.append(cleanup_exc)
            if len(errors) == 1:
                raise
            raise ExceptionGroup(
                "research execution pool construction failed",
                errors,
            ) from exc
        self._workload_cpu_workers = shared_cpu_budget.max_cpu_workers
        self._owner_generation_id = uuid4().hex
        self._exclusive_owner_generation = exclusive_owner_generation
        self._compute_lease_group: TaskGroupPort | None = None
        self._endpoint_lease_group: TaskGroupPort | None = None
        self._environment_lease_group: TaskGroupPort | None = None
        self._container_lease_group: TaskGroupPort | None = None
        self._workloads_quiescing = False
        self._workloads_quiesced = False
        self._closing = False
        self._closed = False

    def _require_workloads_open(self) -> None:
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        if self._closing:
            raise RuntimeError("research execution pool is closing")
        if self._workloads_quiescing or self._workloads_quiesced:
            raise RuntimeError("research execution pool workloads are quiescing")

    @property
    def workload_cpu_workers(self) -> int:
        """Physical CPU workers shared by all workload execution domains."""

        return self._workload_cpu_workers

    @property
    def owner_generation_id(self) -> str:
        """Process-generation fence shared by all schedulers in this pool."""

        return self._owner_generation_id

    @property
    def can_recover_abandoned_owner_generations(self) -> bool:
        """Whether composition proved this pool is the only live local generation."""

        return self._exclusive_owner_generation

    @property
    def model_admission(self) -> ModelAdmissionRegistryPort:
        self._require_workloads_open()
        return self._model_admission

    def open_orchestration_group(
        self,
        group_id: str,
        *,
        tenant_id: str | None = None,
        resource_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        admission_mode: AdmissionMode = AdmissionMode.BLOCK,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort:
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        if self._closing:
            raise RuntimeError("research execution pool is closing")
        return self._orchestration.open_task_group(
            group_id,
            tenant_id=tenant_id,
            resource_id=resource_id,
            priority=priority,
            admission_mode=admission_mode,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    @property
    def control_heartbeats(self):
        """Maintenance heartbeat scheduler isolated from workload admission."""
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        if self._closing:
            raise RuntimeError("research execution pool is closing")
        return self._control.heartbeats

    def open_control_group(
        self,
        group_id: str,
        *,
        tenant_id: str | None = None,
        resource_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.CRITICAL,
        admission_mode: AdmissionMode = AdmissionMode.BLOCK,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort:
        """Open control-plane work that must not be starved by workload capacity."""
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        if self._closing:
            raise RuntimeError("research execution pool is closing")
        return self._control.open_task_group(
            group_id,
            tenant_id=tenant_id,
            resource_id=resource_id,
            priority=priority,
            admission_mode=admission_mode,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    def open_experiment_group(
        self,
        group_id: str,
        *,
        tenant_id: str | None = None,
        resource_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        admission_mode: AdmissionMode = AdmissionMode.BLOCK,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort:
        self._require_workloads_open()
        return self._experiments.open_task_group(
            group_id,
            tenant_id=tenant_id,
            resource_id=resource_id,
            priority=priority,
            admission_mode=admission_mode,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    def compute_lease_guard_factory(
        self,
        scheduler: ComputeSchedulerPort,
        *,
        policy: ComputeLeasePolicy = DEFAULT_COMPUTE_LEASE_POLICY,
        lane_capacity: int | None = 1,
    ) -> ComputeLeaseGuardFactoryPort:
        """Share one structured heartbeat authority across all compute leases."""
        self._require_workloads_open()

        if self._compute_lease_group is None:
            self._compute_lease_group = self._control.open_task_group(
                f"research-compute-leases:{uuid4().hex}",
                resource_id="compute-lease-heartbeats",
                priority=ExecutionPriority.CRITICAL,
                admission_mode=AdmissionMode.BLOCK,
                failure_policy=TaskFailurePolicy.FAIL_FAST,
            )
        return ComputeLeaseHeartbeatFactory(
            scheduler=scheduler,
            task_group=self._compute_lease_group,
            heartbeat_scheduler=self._control.heartbeats,
            lane_id="research-compute-lease-renewal",
            lane_capacity=lane_capacity,
            policy=policy,
        )

    def endpoint_lease_guard_factory(
        self,
        allocations: EndpointAllocationPort,
        *,
        policy: EndpointLeasePolicy = DEFAULT_ENDPOINT_LEASE_POLICY,
        lane_capacity: int | None = 1,
    ) -> EndpointLeaseGuardFactoryPort:
        """Share one structured heartbeat authority across endpoint leases."""
        self._require_workloads_open()

        if self._endpoint_lease_group is None:
            self._endpoint_lease_group = self._control.open_task_group(
                f"research-endpoint-leases:{uuid4().hex}",
                resource_id="endpoint-lease-heartbeats",
                priority=ExecutionPriority.CRITICAL,
                admission_mode=AdmissionMode.BLOCK,
                failure_policy=TaskFailurePolicy.FAIL_FAST,
            )
        return EndpointLeaseHeartbeatFactory(
            allocations=allocations,
            task_group=self._endpoint_lease_group,
            heartbeat_scheduler=self._control.heartbeats,
            lane_id="research-endpoint-lease-renewal",
            lane_capacity=lane_capacity,
            policy=policy,
        )

    def environment_instance_lease_guard_factory(
        self,
        authority: EnvironmentInstanceLeaseAuthority,
        *,
        policy: EnvironmentInstanceLeasePolicy = DEFAULT_ENVIRONMENT_INSTANCE_LEASE_POLICY,
        lane_capacity: int | None = 1,
    ) -> EnvironmentInstanceLeaseHeartbeatFactory:
        """Share one structured heartbeat authority across environment checkouts."""
        self._require_workloads_open()

        if self._environment_lease_group is None:
            self._environment_lease_group = self._control.open_task_group(
                f"research-environment-leases:{uuid4().hex}",
                resource_id="environment-instance-lease-heartbeats",
                priority=ExecutionPriority.CRITICAL,
                admission_mode=AdmissionMode.BLOCK,
                failure_policy=TaskFailurePolicy.FAIL_FAST,
            )
        return EnvironmentInstanceLeaseHeartbeatFactory(
            authority=authority,
            task_group=self._environment_lease_group,
            heartbeat_scheduler=self._control.heartbeats,
            lane_id="research-environment-instance-lease-renewal",
            lane_capacity=lane_capacity,
            policy=policy,
        )

    def docker_container_lease_guard_factory(
        self,
        authority: DockerContainerLeaseAuthority,
        *,
        policy: DockerContainerLeasePolicy = DEFAULT_DOCKER_CONTAINER_LEASE_POLICY,
        lane_capacity: int | None = 1,
    ) -> DockerContainerLeaseHeartbeatFactory:
        """Share one structured heartbeat authority across managed Docker containers."""
        self._require_workloads_open()

        if self._container_lease_group is None:
            self._container_lease_group = self._control.open_task_group(
                f"research-container-leases:{uuid4().hex}",
                resource_id="docker-container-lease-heartbeats",
                priority=ExecutionPriority.CRITICAL,
                admission_mode=AdmissionMode.BLOCK,
                failure_policy=TaskFailurePolicy.FAIL_FAST,
            )
        return DockerContainerLeaseHeartbeatFactory(
            authority=authority,
            task_group=self._container_lease_group,
            heartbeat_scheduler=self._control.heartbeats,
            lane_id="research-docker-container-lease-renewal",
            lane_capacity=lane_capacity,
            policy=policy,
        )

    def open_model_io_group(
        self,
        group_id: str,
        *,
        tenant_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        admission_mode: AdmissionMode = AdmissionMode.BLOCK,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort:
        self._require_workloads_open()
        return self._model_io.open_task_group(
            group_id,
            tenant_id=tenant_id,
            priority=priority,
            admission_mode=admission_mode,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    def close_orchestration_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        self._orchestration.close_task_group(
            group,
            cancel_pending=cancel_pending,
            deadline=deadline,
        )

    def close_control_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        self._control.close_task_group(
            group,
            cancel_pending=cancel_pending,
            deadline=deadline,
        )

    def close_experiment_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        self._experiments.close_task_group(
            group,
            cancel_pending=cancel_pending,
            deadline=deadline,
        )

    def close_model_io_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        self._model_io.close_task_group(
            group,
            cancel_pending=cancel_pending,
            deadline=deadline,
        )

    @staticmethod
    def _close_domain_for_physical_convergence(
        runtime,
        *,
        deadline: Deadline | None,
    ) -> BaseException | None:
        """Close one execution domain and classify only physical non-convergence.

        The concurrency runtime intentionally reports historical logical child
        failures from close() even after every owned task/lane/provider has
        physically joined. Those failures remain visible in topology/evidence
        and through normal task health checks, but they must not pin physical
        resources forever during terminal teardown.
        """

        try:
            runtime.close(deadline=deadline)
        except BaseException as exc:
            snapshot = runtime.topology_snapshot()
            if snapshot.converged:
                return None
            return exc
        return None

    def quiesce_workloads(
        self,
        *,
        deadline: Deadline | None = None,
    ) -> None:
        """Seal and physically join experiment/model-I/O work, keeping control alive.

        Experiments are closed first because they may synchronously wait on
        model-I/O. Resource and durable-ownership heartbeats live in the
        independent control domain and intentionally survive workload quiescence;
        each physical owner stops its own guard only after dependent work has
        converged and the physical effect is safe to release.
        """

        if self._closed or self._workloads_quiesced:
            return
        self._workloads_quiescing = True
        errors: list[BaseException] = []
        experiment_error = self._close_domain_for_physical_convergence(
            self._experiments,
            deadline=deadline,
        )
        if experiment_error is not None:
            errors.append(experiment_error)
        # Even when experiment convergence is unproven, model-I/O still receives
        # a bounded close attempt so shutdown does not strand workers.
        model_io_error = self._close_domain_for_physical_convergence(
            self._model_io,
            deadline=deadline,
        )
        if model_io_error is not None:
            errors.append(model_io_error)
        if errors:
            raise ExceptionGroup(
                "research execution workload quiesce failed",
                errors,
            )
        self._workloads_quiesced = True

    def orchestration_admission_snapshot(self):
        return self._orchestration.admission_snapshot()

    def control_admission_snapshot(self):
        return self._control.admission_snapshot()

    def experiment_admission_snapshot(self):
        return self._experiments.admission_snapshot()

    def model_io_admission_snapshot(self):
        return self._model_io.admission_snapshot()

    def close(self, *, deadline: Deadline | None = None) -> None:
        if self._closed:
            return
        # Seal every workload submission path immediately. Control-plane
        # ownership remains alive until every workload domain and its shared
        # physical CPU provider have converged, so lease/fencing/recovery can
        # still make progress after a bounded close failure.
        self._closing = True
        errors: list[BaseException] = []
        workload_runtimes = (
            self._experiments,
            self._model_io,
            self._orchestration,
        )
        for runtime in workload_runtimes:
            error = self._close_domain_for_physical_convergence(
                runtime,
                deadline=deadline,
            )
            if error is not None:
                errors.append(error)

        workloads_converged = all(
            runtime.topology_snapshot().converged
            for runtime in workload_runtimes
        )
        if workloads_converged and not self._shared_workload_cpu_closed:
            try:
                assert self._shared_workload_cpu is not None
                self._shared_workload_cpu.close(
                    wait=True,
                    cancel_pending=True,
                )
            except BaseException as exc:
                errors.append(exc)
            else:
                self._shared_workload_cpu_closed = True

        if workloads_converged and self._shared_workload_cpu_closed:
            try:
                self._model_admission.close()
            except BaseException as exc:
                errors.append(exc)
            control_error = self._close_domain_for_physical_convergence(
                self._control,
                deadline=deadline,
            )
            if control_error is not None:
                errors.append(control_error)

        if errors:
            raise ExceptionGroup("research execution pool close failed", errors)
        if not workloads_converged or not self._shared_workload_cpu_closed:
            raise RuntimeError(
                "research execution pool close did not converge workload CPU ownership"
            )
        if not self._control.topology_snapshot().converged:
            raise RuntimeError(
                "research execution pool close did not converge control ownership"
            )
        self._closed = True

    def __enter__(self) -> "ResearchExecutionPool":
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        if self._closing:
            raise RuntimeError("research execution pool is closing")
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


__all__ = ["ResearchExecutionPool"]
