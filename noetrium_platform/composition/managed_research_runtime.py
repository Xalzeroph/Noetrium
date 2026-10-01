from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from threading import Event
from typing import Mapping

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentSelector,
    ModelRuntimeState,
)
from noetrium_platform.capabilities.model.deployment.composition import LocalModelReplicaPoolRuntime
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskHandlePort,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.lease.api import (
    DEFAULT_RESOURCE_LEASE_POLICY,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceLeaseCardinality,
    ResourceOwner,
    ResourceOwnership,
)
from noetrium_platform.infrastructure.resources.lease.runtime import LeaseHeartbeatGuard
from noetrium_platform.research.execution.policy.api import AdmissionBudget
from noetrium_platform.research.execution.policy.api import ExecutionPriority
from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayout
from noetrium_platform.infrastructure.resources.directory.runtime import standard_local_directory_layout
from noetrium_platform.infrastructure.resources.compute.providers import LocalHostRuntimeObserver
from noetrium_platform.infrastructure.reliability.recovery.api import (
    RecoveryExecutionFactoryPort,
)
from noetrium_platform.composition.reliability_resources import (
    compose_resource_recovery_lease,
)
from noetrium_platform.infrastructure.reliability.recovery.execution.composition import (
    compose_file_locked_recovery_execution,
)

from .managed_observability import ManagedObservability, build_managed_observability
from .managed_operation_runtime import (
    ManagedOperationRuntime,
    build_managed_operation_runtime,
)
from .managed_research_services import (
    ManagedResearchServices,
    build_managed_research_services,
)
from .model_management import (
    ManagementPlaneAuthorities,
    bind_local_model_replica_pool,
    build_local_management_plane,
)
from .research_execution_pool import ResearchExecutionPool
from .resource_lifecycle import ManagedResourceReconciler
from .runtime_coordination import runtime_fabric_root
from .shared_host_pressure import (
    LocalSharedNetworkPressureObserver,
    LocalSharedStoragePressureObserver,
    ResourceCompetitionPolicy,
)


class _EventStop:
    def __init__(self, event: Event) -> None:
        self._event = event

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)


def _reconcile_startup_ownership(
    management: ManagementPlaneAuthorities,
    resources: ManagedResourceReconciler,
) -> None:
    """Observe durable physical realizations before targeted adoption.

    Generic resource reconciliation is deliberately deferred until required
    model/environment realizations have had a chance to reacquire their exact
    leases. Running it here would destroy warm state after an idle TTL gap.
    """

    del resources
    management.models.fleet.status_all()


@dataclass(slots=True)
class ManagedResearchRuntime:
    """Composition owner for one long-lived platform research process.

    This owns no scheduling/model/run semantics. It only binds already-existing
    authorities to one structured-concurrency lifetime so downstream code cannot
    accidentally bypass resource admission, model reconciliation, automatic
    model placement, lease renewal, or shutdown.
    """

    execution_pool: ResearchExecutionPool
    management: ManagementPlaneAuthorities
    observability: ManagedObservability
    operation_runtime: ManagedOperationRuntime
    recovery_execution: RecoveryExecutionFactoryPort
    services: ManagedResearchServices
    _orchestration_group: TaskGroupPort
    _docker_group: TaskGroupPort
    _stop: Event
    resources: ManagedResourceReconciler
    _runtime_lock: InterprocessFileLock
    model_replica_pool: LocalModelReplicaPoolRuntime | None = None
    _fabric_consumer_resource: ResourceIdentity | None = None
    _fabric_consumer_lease: ResourceLease | None = None
    _fabric_consumer_guard: LeaseHeartbeatGuard | None = None
    _fabric_coordination_lock_path: Path | None = None
    _fabric_consumer_released: bool = False
    _model_controller: TaskHandlePort | None = None
    _resource_controller: TaskHandlePort | None = None
    _closing: bool = False
    _controllers_quiesced: bool = False
    _workloads_quiesced: bool = False
    _auto_model_leases_closed: bool = False
    _auto_models_removed: bool = False
    _models_stopped: bool = False
    _resources_cleaned: bool = False
    _operation_runtime_closed: bool = False
    _observability_closed: bool = False
    _docker_group_closed: bool = False
    _orchestration_closed: bool = False
    _pool_closed: bool = False
    _lock_released: bool = False
    _closed: bool = False

    def _attach_runtime_fabric_consumer(self, coordination_lock_path: Path) -> None:
        """Publish this live runtime as one fenced Runtime Fabric consumer."""

        if self._fabric_consumer_lease is not None:
            raise RuntimeError("Runtime Fabric consumer is already attached")
        lock_path = Path(coordination_lock_path).expanduser().absolute()
        resource = ResourceIdentity(
            ResourceKind.RUNTIME_FABRIC,
            "host-runtime-fabric",
        )
        owner = ResourceOwner(
            resource,
            PLATFORM_SCOPE,
            ResourceOwnership.SHARED,
            ResourceLeaseCardinality.MULTI_ACTIVE,
        )
        lease = ResourceLease(
            lease_id=f"runtime-fabric-consumer:{self.execution_pool.owner_generation_id}",
            resource=resource,
            holder_scope=PLATFORM_SCOPE,
            purpose="runtime-fabric-consumer",
        )
        leases = self.management.platform_meta.resource_leases
        ownership = self.management.platform_meta.resource_ownership
        granted = None
        with InterprocessFileLock(lock_path):
            ownership.register_owner(owner)
            try:
                granted = leases.acquire(
                    lease,
                    ttl_seconds=DEFAULT_RESOURCE_LEASE_POLICY.ttl_seconds,
                )
            except BaseException:
                raise
        guard = self.execution_pool.resource_lease_guard_factory(
            leases,
            policy=DEFAULT_RESOURCE_LEASE_POLICY,
        ).create((granted,))
        try:
            guard.start()
        except BaseException:
            with InterprocessFileLock(lock_path):
                leases.release(
                    granted.lease_id,
                    fencing_token=granted.fencing_token,
                )
            raise
        self._fabric_consumer_resource = resource
        self._fabric_consumer_lease = granted
        self._fabric_consumer_guard = guard
        self._fabric_coordination_lock_path = lock_path
        self._fabric_consumer_released = False

    def _release_runtime_fabric_consumer(self, *, coordination_locked: bool = False) -> None:
        if self._fabric_consumer_released:
            return
        resource = self._fabric_consumer_resource
        lease = self._fabric_consumer_lease
        guard = self._fabric_consumer_guard
        lock_path = self._fabric_coordination_lock_path
        if resource is None or lease is None or guard is None or lock_path is None:
            self._fabric_consumer_released = True
            return
        guard.assert_healthy()
        current_rows = guard.rows
        if len(current_rows) != 1:
            raise RuntimeError("Runtime Fabric consumer heartbeat cardinality drifted")
        current = current_rows[0]
        guard.close()

        def release() -> None:
            released = self.management.platform_meta.resource_leases.release(
                current.lease_id,
                fencing_token=current.fencing_token,
            )
            if released.state.value != "released":
                raise RuntimeError("Runtime Fabric consumer lease did not release")

        if coordination_locked:
            release()
        else:
            with InterprocessFileLock(lock_path):
                release()
        self._fabric_consumer_lease = current
        self._fabric_consumer_released = True

    def retire_runtime_fabric(self) -> None:
        """Terminally retire shared physical realizations after a global zero-consumer proof."""

        if self._closed:
            raise RuntimeError("managed research runtime is closed")
        if self._closing:
            raise RuntimeError("managed research runtime is already closing")
        lock_path = self._fabric_coordination_lock_path
        if lock_path is None:
            raise RuntimeError("Runtime Fabric terminal retirement requires consumer fencing")

        # Admission and terminal retirement share this host-visible fence. A
        # failed zero-consumer proof is side-effect free; once the proof passes
        # the fence stays held until physical teardown and our own consumer
        # release converge, so no new project can race into the teardown.
        with InterprocessFileLock(lock_path):
            resource = self._fabric_consumer_resource
            if resource is None:
                raise RuntimeError("Runtime Fabric terminal retirement lost resource identity")
            active = self.management.platform_meta.resource_leases.active_for(resource)
            own_ids = {
                row.lease_id
                for row in (
                    ()
                    if self._fabric_consumer_guard is None
                    else self._fabric_consumer_guard.rows
                )
            }
            foreign = tuple(row for row in active if row.lease_id not in own_ids)
            if foreign:
                raise RuntimeError(
                    "Runtime Fabric terminal retirement refused with active consumers: "
                    + ",".join(row.lease_id for row in foreign)
                )

            self._closing = True
            if not self._controllers_quiesced:
                self.quiesce_background_controllers()
                self._controllers_quiesced = True
            if not self._workloads_quiesced:
                self.execution_pool.quiesce_workloads()
                self._workloads_quiesced = True

            if not self._auto_model_leases_closed:
                if self.model_replica_pool is not None:
                    self.model_replica_pool.close_all()
                self._auto_model_leases_closed = True
            if not self._auto_models_removed:
                self.management.models.fleet.remove_selected(
                    ModelDeploymentSelector(tags=("auto-managed",))
                )
                self._auto_models_removed = True
            if not self._models_stopped:
                statuses = self.management.models.fleet.shutdown_all()
                failed = tuple(
                    row
                    for row in statuses
                    if row.runtime_state
                    not in {ModelRuntimeState.STOPPED, ModelRuntimeState.MISSING}
                )
                if failed:
                    raise RuntimeError(
                        "model processes survived Runtime Fabric retirement: "
                        + ",".join(
                            f"{row.deployment_id}:{row.runtime_state.value}"
                            for row in failed
                        )
                    )
                self._models_stopped = True
            if not self._resources_cleaned:
                self.resources.shutdown_cleanup()
                self._resources_cleaned = True
            self._release_runtime_fabric_consumer(coordination_locked=True)
            remaining = self.management.platform_meta.resource_leases.active_for(resource)
            if remaining:
                raise RuntimeError(
                    "Runtime Fabric consumer leases appeared during terminal retirement"
                )

        self.close()

    def start_background_controllers(
        self,
        *,
        model_reconcile_interval_seconds: float = 10.0,
        resource_reconcile_interval_seconds: float = 30.0,
    ) -> None:
        if self._closed:
            raise RuntimeError("managed research runtime is closed")
        if self._closing:
            raise RuntimeError("managed research runtime is closing")
        if self._stop.is_set():
            raise RuntimeError("managed research runtime is quiescing")

        def _interval(value: float, label: str) -> float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{label} reconcile interval must be a real number")
            resolved = float(value)
            if not math.isfinite(resolved) or resolved <= 0:
                raise ValueError(
                    f"{label} reconcile interval must be finite and positive"
                )
            return resolved

        model_interval = _interval(
            model_reconcile_interval_seconds,
            "model",
        )
        resource_interval = _interval(
            resource_reconcile_interval_seconds,
            "resource",
        )
        stop = _EventStop(self._stop)

        # TaskGroup callables use the kernel task ABI and receive the task
        # ExecutionContext as their first positional argument.  Model/resource
        # controllers are lower-layer lifecycle ports with keyword-only run()
        # contracts, so this composition boundary must absorb that context
        # rather than leaking TaskGroup semantics into the controller APIs.
        def run_model_controller(_context):
            return self.management.models.controller.run(
                interval_seconds=model_interval,
                stop=stop,
            )

        def run_resource_controller(_context):
            return self.resources.run(
                interval_seconds=resource_interval,
                stop=stop,
            )

        if self._model_controller is None or self._model_controller.done():
            self._model_controller = self._orchestration_group.submit(
                ExecutionSpec(
                    task_id="managed-model-desired-state-controller",
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                ),
                run_model_controller,
            )
        if self._resource_controller is None or self._resource_controller.done():
            self._resource_controller = self._orchestration_group.submit(
                ExecutionSpec(
                    task_id="managed-resource-reconciler",
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                ),
                run_resource_controller,
            )

    def quiesce_background_controllers(self) -> None:
        """Stop long-lived controllers without closing the shared execution pool."""

        self._stop.set()
        errors: list[BaseException] = []
        for controller in (self._model_controller, self._resource_controller):
            if controller is not None:
                try:
                    controller.result(timeout=30.0)
                except BaseException as exc:
                    errors.append(exc)
        if errors:
            raise ExceptionGroup(
                "managed research runtime quiesce failed",
                errors,
            )

    def assert_healthy(self) -> None:
        if self._closed:
            raise RuntimeError("managed research runtime is closed")
        if self._closing:
            raise RuntimeError("managed research runtime is closing")
        self._orchestration_group.assert_healthy()
        self._docker_group.assert_healthy()
        for controller in (self._model_controller, self._resource_controller):
            if controller is not None and controller.done():
                controller.result()
        if self._fabric_consumer_guard is not None and not self._fabric_consumer_released:
            self._fabric_consumer_guard.assert_healthy()

    @staticmethod
    def _close_stage_error(stage: str, error: BaseException) -> ExceptionGroup:
        nested = (
            list(error.exceptions)
            if isinstance(error, BaseExceptionGroup)
            else [error]
        )
        return ExceptionGroup(
            f"managed research runtime close failed during {stage}",
            nested,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closing = True

        if not self._controllers_quiesced:
            try:
                self.quiesce_background_controllers()
            except BaseException as exc:
                raise self._close_stage_error("controller quiescence", exc)
            self._controllers_quiesced = True

        if not self._workloads_quiesced:
            try:
                self.execution_pool.quiesce_workloads()
            except BaseException as exc:
                raise self._close_stage_error("workload quiescence", exc)
            self._workloads_quiesced = True

        # Exact in-process replica-pool owners must converge first.  Their lease
        # objects own the live heartbeat generations as well as the model ->
        # endpoint/compute teardown order.  Generic desired-state retirement is
        # only the recovery path for auto-managed generations not represented
        # by a surviving in-process lease.
        if not self._auto_model_leases_closed:
            try:
                if self.model_replica_pool is not None:
                    self.model_replica_pool.detach_all()
            except BaseException as exc:
                raise self._close_stage_error(
                    "auto-managed replica lease retirement",
                    exc,
                )
            self._auto_model_leases_closed = True

        if not self._fabric_consumer_released:
            try:
                self._release_runtime_fabric_consumer()
            except BaseException as exc:
                raise self._close_stage_error("Runtime Fabric consumer release", exc)

        # This runtime owns consumers, not durable physical realizations.
        self._auto_models_removed = True
        self._models_stopped = True

        # Normal run shutdown detaches consumers; it must not run generic
        # resource GC here. Required realizations stay warm across runs and are
        # targeted-adopted before the next background reconciliation cycle.
        self._resources_cleaned = True

        if not self._operation_runtime_closed:
            try:
                self.operation_runtime.close()
            except BaseException as exc:
                raise self._close_stage_error("operation/forensics shutdown", exc)
            self._operation_runtime_closed = True

        if not self._observability_closed:
            try:
                self.observability.close()
            except BaseException as exc:
                raise self._close_stage_error("observability shutdown", exc)
            self._observability_closed = True

        if not self._docker_group_closed:
            try:
                self.execution_pool.close_control_group(
                    self._docker_group,
                    cancel_pending=True,
                )
            except BaseException as exc:
                raise self._close_stage_error("Docker I/O group shutdown", exc)
            self._docker_group_closed = True

        if not self._orchestration_closed:
            try:
                self.execution_pool.close_orchestration_group(
                    self._orchestration_group,
                    cancel_pending=True,
                )
            except BaseException as exc:
                raise self._close_stage_error("orchestration shutdown", exc)
            self._orchestration_closed = True

        if not self._pool_closed:
            try:
                self.execution_pool.close()
            except BaseException as exc:
                raise self._close_stage_error("execution-pool shutdown", exc)
            self._pool_closed = True

        # This lock is the final local ownership fence. It is intentionally
        # retained after any earlier failure so a second runtime cannot adopt
        # resources while this process has not yet proved convergence.
        if not self._lock_released:
            try:
                self._runtime_lock.__exit__(None, None, None)
            except BaseException as exc:
                raise self._close_stage_error("runtime-lock release", exc)
            self._lock_released = True

        self._closed = True

    def __enter__(self) -> "ManagedResearchRuntime":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


def build_local_managed_research_runtime(
    layout: DirectoryLayout,
    *,
    base_service_environment: tuple[tuple[str, str], ...] = (),
    model_source_environment: tuple[tuple[str, str], ...] = (),
    huggingface_cli: str = "hf",
    model_storage_pools: Mapping[str, Path] | None = None,
    orchestration_concurrency_budget: ConcurrencyBudget | None = None,
    orchestration_admission_budget: AdmissionBudget | None = None,
    experiment_concurrency_budget: ConcurrencyBudget | None = None,
    experiment_admission_budget: AdmissionBudget | None = None,
    capability_io_concurrency_budget: ConcurrencyBudget | None = None,
    capability_io_admission_budget: AdmissionBudget | None = None,
    model_io_concurrency_budget: ConcurrencyBudget | None = None,
    model_io_admission_budget: AdmissionBudget | None = None,
    start_background_controllers: bool = True,
    model_reconcile_interval_seconds: float = 10.0,
    resource_reconcile_interval_seconds: float = 30.0,
    resource_competition_policy: ResourceCompetitionPolicy | None = None,
    runtime_fabric_root_path: Path | None = None,
) -> ManagedResearchRuntime:
    runtime_lock = InterprocessFileLock(
        layout.locks / "managed-research-runtime.lock",
        blocking=False,
    )
    runtime_lock.__enter__()
    pool: ResearchExecutionPool | None = None
    operation_runtime: ManagedOperationRuntime | None = None
    runtime: ManagedResearchRuntime | None = None
    try:
        fabric_root = (
            runtime_fabric_root()
            if runtime_fabric_root_path is None
            else runtime_fabric_root_path.expanduser().absolute()
        )
        fabric_layout = standard_local_directory_layout(fabric_root / "runtime")
        durable_fabric_layout = standard_local_directory_layout(
            fabric_root / "content"
        )
        host_pressure_observer = LocalHostRuntimeObserver()
        storage_pressure_observer = LocalSharedStoragePressureObserver(
            tuple(
                dict.fromkeys(
                    path
                    for authority_layout in (layout, fabric_layout, durable_fabric_layout)
                    for _kind, path in authority_layout.entries()
                )
            )
        )
        network_pressure_observer = LocalSharedNetworkPressureObserver()
        pool = ResearchExecutionPool(
        orchestration_concurrency_budget=orchestration_concurrency_budget,
        orchestration_admission_budget=orchestration_admission_budget,
        experiment_concurrency_budget=experiment_concurrency_budget,
        experiment_admission_budget=experiment_admission_budget,
        capability_io_concurrency_budget=capability_io_concurrency_budget,
        capability_io_admission_budget=capability_io_admission_budget,
        model_io_concurrency_budget=model_io_concurrency_budget,
        model_io_admission_budget=model_io_admission_budget,
        host_runtime_observer=host_pressure_observer,
        storage_pressure_observer=storage_pressure_observer,
        network_pressure_observer=network_pressure_observer,
        resource_competition_policy=resource_competition_policy,
        exclusive_owner_generation=True,
        )
        group = pool.open_orchestration_group(
            "managed-research-runtime",
            resource_id="platform-runtime-controller",
            priority=ExecutionPriority.CRITICAL,
        )
        docker_group = pool.open_control_group(
            "managed-research-runtime-docker-io",
            resource_id="docker-management-io",
            priority=ExecutionPriority.CRITICAL,
        )
        try:
            management = build_local_management_plane(
                layout,
                durable_layout=durable_fabric_layout,
                physical_layout=fabric_layout,
                base_service_environment=base_service_environment,
                model_source_environment=model_source_environment,
                huggingface_cli=huggingface_cli,
                model_storage_pools=model_storage_pools,
                task_group=group,
                docker_task_group=docker_group,
                execution_pool=pool,
            )
            # Startup reconciliation is synchronous and fail-closed. No new
            # workload is admitted until physical owners are converged and then
            # their logical/ephemeral resources agree after restart.
            resources = ManagedResourceReconciler(
                containers=management.docker_containers,
                environments=management.platform_meta.environment_instance_leases,
                endpoints=management.platform_meta.endpoint_allocations,
                compute=management.platform_meta.compute_scheduler,
            )
            _reconcile_startup_ownership(management, resources)
            model_replica_pool = bind_local_model_replica_pool(management, pool)
        except BaseException:
            pool.close_control_group(docker_group, cancel_pending=True)
            pool.close_orchestration_group(group, cancel_pending=True)
            raise
        operation_runtime = build_managed_operation_runtime(
            layout.state / "operations",
            task_group=group,
        )
        observability = build_managed_observability(
            layout.state / "observability",
            task_group=group,
            systems=management.platform_meta.systems,
            planner=management.platform_meta.capability_composition,
        )
        services = build_managed_research_services(
            layout.state / "research-services",
            meta=management.platform_meta,
        )
        recovery_lease = compose_resource_recovery_lease(
            management.platform_meta.resource_ownership,
            management.platform_meta.resource_leases,
            evidence_refs=("managed-research-runtime",),
        )
        recovery_execution = compose_file_locked_recovery_execution(
            recovery_lease,
            lock_path=layout.locks / "recovery.execution.lock",
        )
        runtime = ManagedResearchRuntime(
            execution_pool=pool,
            management=management,
            observability=observability,
            operation_runtime=operation_runtime,
            recovery_execution=recovery_execution,
            services=services,
            _orchestration_group=group,
            _docker_group=docker_group,
            _stop=Event(),
            resources=resources,
            _runtime_lock=runtime_lock,
            model_replica_pool=model_replica_pool,
        )
        runtime._attach_runtime_fabric_consumer(
            fabric_layout.locks / "runtime-fabric-consumers.lock"
        )
        if start_background_controllers:
            runtime.start_background_controllers(
                model_reconcile_interval_seconds=model_reconcile_interval_seconds,
                resource_reconcile_interval_seconds=resource_reconcile_interval_seconds,
            )
        return runtime
    except BaseException as primary:
        errors: list[BaseException] = [primary]
        if runtime is not None:
            try:
                runtime.close()
            except BaseException as cleanup:
                errors.append(cleanup)
        else:
            if operation_runtime is not None:
                try:
                    operation_runtime.close()
                except BaseException as cleanup:
                    errors.append(cleanup)
            if pool is not None:
                try:
                    pool.close()
                except BaseException as cleanup:
                    errors.append(cleanup)
            try:
                runtime_lock.__exit__(None, None, None)
            except BaseException as cleanup:
                errors.append(cleanup)
        if len(errors) > 1:
            raise BaseExceptionGroup(
                "managed research runtime construction and cleanup failed",
                errors,
            ) from primary
        raise


__all__ = [
    "ManagedResearchRuntime",
    "build_local_managed_research_runtime",
]
