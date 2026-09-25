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
)
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)
from noetrium_platform.research.execution.policy.api import AdmissionBudget
from noetrium_platform.research.execution.policy.api import ExecutionPriority
from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayout
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
    """Converge process owners before reclaiming their lower resource leases."""

    management.models.fleet.remove_selected(
        ModelDeploymentSelector(tags=("auto-managed",))
    )
    resources.recover_abandoned_owner_generation()


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
    recovery_execution: RecoveryExecutionFactoryPort
    services: ManagedResearchServices
    _orchestration_group: object
    _stop: Event
    resources: ManagedResourceReconciler
    _runtime_lock: InterprocessFileLock
    model_replica_pool: LocalModelReplicaPoolRuntime | None = None
    _model_controller: TaskHandlePort | None = None
    _resource_controller: TaskHandlePort | None = None
    _closing: bool = False
    _controllers_quiesced: bool = False
    _workloads_quiesced: bool = False
    _auto_model_leases_closed: bool = False
    _auto_models_removed: bool = False
    _models_stopped: bool = False
    _resources_cleaned: bool = False
    _observability_closed: bool = False
    _orchestration_closed: bool = False
    _pool_closed: bool = False
    _lock_released: bool = False
    _closed: bool = False

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
        if self._model_controller is None or self._model_controller.done():
            self._model_controller = self._orchestration_group.submit(
                ExecutionSpec(
                    task_id="managed-model-desired-state-controller",
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                ),
                self.management.models.controller.run,
                interval_seconds=model_interval,
                stop=stop,
            )
        if self._resource_controller is None or self._resource_controller.done():
            self._resource_controller = self._orchestration_group.submit(
                ExecutionSpec(
                    task_id="managed-resource-reconciler",
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                ),
                self.resources.run,
                interval_seconds=resource_interval,
                stop=stop,
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
        for controller in (self._model_controller, self._resource_controller):
            if controller is not None and controller.done():
                controller.result()

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
                    self.model_replica_pool.close_all()
            except BaseException as exc:
                raise self._close_stage_error(
                    "auto-managed replica lease retirement",
                    exc,
                )
            self._auto_model_leases_closed = True

        # Automatically placed replicas own ephemeral resource claims for this
        # runtime lifetime.  Their desired specs must not survive past the
        # lease/heartbeat owner generation: a later process must place them
        # again and obtain fresh endpoint/compute fencing.  This catches
        # generations recovered from a prior crash that have no live lease
        # object in this process.
        if not self._auto_models_removed:
            try:
                self.management.models.fleet.remove_selected(
                    ModelDeploymentSelector(tags=("auto-managed",))
                )
            except BaseException as exc:
                raise self._close_stage_error(
                    "auto-managed model retirement",
                    exc,
                )
            self._auto_models_removed = True

        # Remaining explicit durable model deployments may keep desired state,
        # but their physical processes still sit above resource cleanup.
        # Releasing lower resources before every service is physically gone
        # would permit split ownership after restart.
        if not self._models_stopped:
            try:
                statuses = self.management.models.fleet.shutdown_all()
                failed = tuple(
                    row
                    for row in statuses
                    if row.runtime_state
                    not in {ModelRuntimeState.STOPPED, ModelRuntimeState.MISSING}
                )
                if failed:
                    raise RuntimeError(
                        "model processes survived runtime shutdown: "
                        + ",".join(
                            f"{row.deployment_id}:{row.runtime_state.value}"
                            for row in failed
                        )
                    )
            except BaseException as exc:
                raise self._close_stage_error("model shutdown", exc)
            self._models_stopped = True

        if not self._resources_cleaned:
            try:
                self.resources.shutdown_cleanup()
            except BaseException as exc:
                raise self._close_stage_error("resource cleanup", exc)
            self._resources_cleaned = True

        if not self._observability_closed:
            try:
                self.observability.close()
            except BaseException as exc:
                raise self._close_stage_error("observability shutdown", exc)
            self._observability_closed = True

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
    model_io_concurrency_budget: ConcurrencyBudget | None = None,
    model_io_admission_budget: AdmissionBudget | None = None,
    start_background_controllers: bool = True,
    model_reconcile_interval_seconds: float = 10.0,
    resource_reconcile_interval_seconds: float = 30.0,
    resource_competition_policy: ResourceCompetitionPolicy | None = None,
) -> ManagedResearchRuntime:
    runtime_lock = InterprocessFileLock(
        layout.locks / "managed-research-runtime.lock",
        blocking=False,
    )
    runtime_lock.__enter__()
    pool: ResearchExecutionPool | None = None
    try:
        host_pressure_observer = LocalHostRuntimeObserver()
        storage_pressure_observer = LocalSharedStoragePressureObserver(
            tuple(path for _kind, path in layout.entries())
        )
        network_pressure_observer = LocalSharedNetworkPressureObserver()
        pool = ResearchExecutionPool(
        orchestration_concurrency_budget=orchestration_concurrency_budget,
        orchestration_admission_budget=orchestration_admission_budget,
        experiment_concurrency_budget=experiment_concurrency_budget,
        experiment_admission_budget=experiment_admission_budget,
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
        try:
            management = build_local_management_plane(
                layout,
                base_service_environment=base_service_environment,
                model_source_environment=model_source_environment,
                huggingface_cli=huggingface_cli,
                model_storage_pools=model_storage_pools,
                task_group=group,
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
            pool.close_orchestration_group(group, cancel_pending=True)
            raise
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
            recovery_execution=recovery_execution,
            services=services,
            _orchestration_group=group,
            _stop=Event(),
            resources=resources,
            _runtime_lock=runtime_lock,
            model_replica_pool=model_replica_pool,
        )
        if start_background_controllers:
            runtime.start_background_controllers(
                model_reconcile_interval_seconds=model_reconcile_interval_seconds,
                resource_reconcile_interval_seconds=resource_reconcile_interval_seconds,
            )
        return runtime
    except BaseException:
        if pool is not None:
            pool.close()
        runtime_lock.__exit__(None, None, None)
        raise


__all__ = [
    "ManagedResearchRuntime",
    "build_local_managed_research_runtime",
]
