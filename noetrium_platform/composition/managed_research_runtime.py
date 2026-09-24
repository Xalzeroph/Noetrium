from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from threading import Event
from typing import Mapping

from noetrium_platform.capabilities.model.deployment.composition import LocalModelReplicaPoolRuntime
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskHandlePort,
)
from noetrium_platform.research.execution.policy.api import AdmissionBudget
from noetrium_platform.research.execution.policy.api import ExecutionPriority
from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayout
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


class _EventStop:
    def __init__(self, event: Event) -> None:
        self._event = event

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)


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
    model_replica_pool: LocalModelReplicaPoolRuntime | None = None
    _model_controller: TaskHandlePort | None = None
    _resource_controller: TaskHandlePort | None = None
    _closed: bool = False

    def start_background_controllers(
        self,
        *,
        model_reconcile_interval_seconds: float = 10.0,
        resource_reconcile_interval_seconds: float = 30.0,
    ) -> None:
        if self._closed:
            raise RuntimeError("managed research runtime is closed")
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
        self._orchestration_group.assert_healthy()
        for controller in (self._model_controller, self._resource_controller):
            if controller is not None and controller.done():
                controller.result()

    def close(self) -> None:
        if self._closed:
            return
        errors: list[BaseException] = []
        try:
            self.quiesce_background_controllers()
        except BaseException as exc:
            errors.append(exc)
        self._closed = True
        try:
            self.observability.close()
        except BaseException as exc:
            errors.append(exc)
        try:
            self.execution_pool.close_orchestration_group(
                self._orchestration_group,
                cancel_pending=True,
            )
        except BaseException as exc:
            errors.append(exc)
        try:
            self.execution_pool.close()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            first = errors[0]
            raise RuntimeError(
                f"managed research runtime close failed: "
                f"{type(first).__name__}: {first}"
            ) from first

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
) -> ManagedResearchRuntime:
    pool = ResearchExecutionPool(
        orchestration_concurrency_budget=orchestration_concurrency_budget,
        orchestration_admission_budget=orchestration_admission_budget,
        experiment_concurrency_budget=experiment_concurrency_budget,
        experiment_admission_budget=experiment_admission_budget,
        model_io_concurrency_budget=model_io_concurrency_budget,
        model_io_admission_budget=model_io_admission_budget,
    )
    try:
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
            # workload is admitted until physical and logical ephemeral
            # resources agree after a process/daemon/host restart.
            resources = ManagedResourceReconciler(
                containers=management.docker_containers,
                environments=management.platform_meta.environment_instance_leases,
                endpoints=management.platform_meta.endpoint_allocations,
                compute=management.platform_meta.compute_scheduler,
            )
            resources.reconcile()
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
            model_replica_pool=model_replica_pool,
        )
        if start_background_controllers:
            runtime.start_background_controllers(
                model_reconcile_interval_seconds=model_reconcile_interval_seconds,
                resource_reconcile_interval_seconds=resource_reconcile_interval_seconds,
            )
        return runtime
    except BaseException:
        pool.close()
        raise


__all__ = [
    "ManagedResearchRuntime",
    "build_local_managed_research_runtime",
]
