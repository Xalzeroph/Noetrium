from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentSelector,
    ModelRuntimeState,
)
from noetrium_platform.capabilities.model.deployment.composition import LocalModelReplicaPoolRuntime
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE, scope_key
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.unit_codec import UNIT_DOCUMENT_SCHEMA
from noetrium_platform.infrastructure.resources.authority import claim_field
from noetrium_platform.infrastructure.resources.authority import (
    DEFAULT_AUTHORITY_LEASE_POLICY,
    LeaseHeartbeatGuard,
    UniversalResourceAuthority,
)
from noetrium_platform.foundation.kernel.kernel.lease_clock import LocalLeaseClock
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
from .runtime_coordination import runtime_fabric_root
from .shared_host_pressure import (
    LocalSharedNetworkPressureObserver,
    LocalSharedStoragePressureObserver,
    ResourceCompetitionPolicy,
)




def _persistence_scoped_layout(layout: DirectoryLayout) -> DirectoryLayout:
    """Isolate non-compatible durable state while preserving reusable caches.

    Noetrium has no persistence compatibility path. A Unit document epoch
    change therefore creates a new authority-state namespace, while logs,
    content-addressed artifacts, environments and caches retain their stable
    host-fabric locations.
    """

    if not isinstance(layout, DirectoryLayout):
        raise TypeError("runtime fabric persistence layout requires DirectoryLayout")
    return replace(layout, state=layout.state / UNIT_DOCUMENT_SCHEMA)

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
    _runtime_lock: InterprocessFileLock
    model_replica_pool: LocalModelReplicaPoolRuntime | None = None
    _fabric_consumer_resource: str | None = None
    _fabric_consumer_lease: NoetriumUnit | None = None
    _fabric_consumer_guard: LeaseHeartbeatGuard | None = None
    _fabric_coordination_lock_path: Path | None = None
    _fabric_consumer_released: bool = False
    _closing: bool = False
    _workloads_quiesced: bool = False
    _auto_model_leases_closed: bool = False
    _auto_models_removed: bool = False
    _models_stopped: bool = False
    _operation_runtime_closed: bool = False
    _observability_closed: bool = False
    _docker_group_closed: bool = False
    _orchestration_closed: bool = False
    _pool_closed: bool = False
    _lock_released: bool = False
    _closed: bool = False

    def _attach_runtime_fabric_consumer(
        self,
        coordination_lock_path: Path,
        *,
        holder_scope: NoetriumUnit = PLATFORM_SCOPE,
        holder_scope_lease: NoetriumUnit | None = None,
    ) -> None:
        """Attach this runtime as one Universal Authority consumer lease."""

        if not isinstance(holder_scope, NoetriumUnit):
            raise TypeError("Runtime Fabric consumer holder_scope must be NoetriumUnit")
        if self._fabric_consumer_lease is not None:
            raise RuntimeError("Runtime Fabric consumer is already attached")
        lock_path = Path(coordination_lock_path).expanduser().absolute()
        resource_key = "runtime-fabric:host-runtime-fabric"
        authority = self.management.platform_meta.resource_authority
        lease_id = (
            "runtime-fabric-consumer:"
            + self.execution_pool.owner_generation_id
        )
        # The lock only serializes local physical controller startup. Dynamic
        # ownership/fencing truth is committed by UniversalResourceAuthority.
        with InterprocessFileLock(lock_path):
            granted = authority.acquire_ttl_lease(
                lease_id=lease_id,
                resource_key=resource_key,
                holder_key=scope_key(holder_scope),
                owner_scope=holder_scope,
                scope_lease=holder_scope_lease,
                ttl_seconds=DEFAULT_AUTHORITY_LEASE_POLICY.ttl_seconds,
                metadata={"kind": "runtime-fabric-consumer"},
            )
        guard = self.execution_pool.resource_lease_guard_factory(
            authority,
            policy=DEFAULT_AUTHORITY_LEASE_POLICY,
        ).create((granted,))
        try:
            guard.start()
        except BaseException:
            authority.release_lease(granted)
            raise
        self._fabric_consumer_resource = resource_key
        self._fabric_consumer_lease = granted
        self._fabric_consumer_guard = guard
        self._fabric_coordination_lock_path = lock_path
        self._fabric_consumer_released = False

    def _release_runtime_fabric_consumer(
        self,
        *,
        coordination_locked: bool = False,
    ) -> None:
        if self._fabric_consumer_released:
            return
        resource_key = self._fabric_consumer_resource
        lease = self._fabric_consumer_lease
        guard = self._fabric_consumer_guard
        lock_path = self._fabric_coordination_lock_path
        if resource_key is None or lease is None or guard is None or lock_path is None:
            self._fabric_consumer_released = True
            return
        current_rows = guard.rows
        if len(current_rows) != 1:
            raise RuntimeError("Runtime Fabric consumer heartbeat cardinality drifted")
        last_owned = current_rows[0]
        guard.close()
        authority = self.management.platform_meta.resource_authority

        def release() -> NoetriumUnit:
            return authority.release_lease(last_owned)

        if coordination_locked:
            final = release()
        else:
            with InterprocessFileLock(lock_path):
                final = release()
        self._fabric_consumer_lease = final
        self._fabric_consumer_released = True

    def retire_runtime_fabric(self) -> None:
        """Terminally retire shared realizations under one Authority fence."""

        if self._closed:
            raise RuntimeError("managed research runtime is closed")
        if self._closing:
            raise RuntimeError("managed research runtime is already closing")
        lock_path = self._fabric_coordination_lock_path
        resource_key = self._fabric_consumer_resource
        if lock_path is None or resource_key is None:
            raise RuntimeError(
                "Runtime Fabric terminal retirement requires consumer fencing"
            )
        authority = self.management.platform_meta.resource_authority
        own_leases = tuple(
            () if self._fabric_consumer_guard is None else self._fabric_consumer_guard.rows
        )

        with InterprocessFileLock(lock_path):
            gate = authority.fence_if_no_live_leases(
                resource_key,
                holder_key=(
                    "runtime-fabric-retirement:"
                    + self.execution_pool.owner_generation_id
                ),
                excluding_leases=own_leases,
            )
            try:
                self._closing = True
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
                self._release_runtime_fabric_consumer(coordination_locked=True)
            except BaseException:
                # Gate remains fail-closed when physical retirement is incomplete.
                raise
            authority.release_claim(str(claim_field(gate, "claim_id")))

        self.close()

    @property
    def workloads_quiescent(self) -> bool:
        return self._workloads_quiesced or self.execution_pool.workloads_quiescent

    def quiesce_workloads(self) -> None:
        """Seal and join workload borrowers while control ownership stays live."""
        if self._closed:
            return
        if self._workloads_quiesced:
            return
        self.execution_pool.quiesce_workloads()
        self._workloads_quiesced = True

    def assert_healthy(self) -> None:
        if self._closed:
            raise RuntimeError("managed research runtime is closed")
        if self._closing:
            raise RuntimeError("managed research runtime is closing")
        self._orchestration_group.assert_healthy()
        self._docker_group.assert_healthy()
        if self._fabric_consumer_guard is not None and not self._fabric_consumer_released:
            self._fabric_consumer_guard.assert_healthy()

    @staticmethod
    def _close_stage_error(stage: str, error: BaseException) -> BaseExceptionGroup:
        nested = (
            list(error.exceptions)
            if isinstance(error, BaseExceptionGroup)
            else [error]
        )
        return BaseExceptionGroup(
            f"managed research runtime close failed during {stage}",
            nested,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closing = True
        errors: list[BaseException] = []

        def attempt(stage: str, action, *, mark=None) -> bool:
            try:
                action()
            except BaseException as exc:
                errors.append(self._close_stage_error(stage, exc))
                return False
            if mark is not None:
                mark()
            return True

        if not self._workloads_quiesced:
            attempt(
                "workload quiescence",
                self.quiesce_workloads,
            )

        # Exact in-process replica-pool owners must converge first. Their lease
        # objects own the live heartbeat generations as well as model ->
        # endpoint/compute teardown order. Failure is recorded, but does not
        # prevent independent owners from receiving their close attempt.
        if not self._auto_model_leases_closed:
            def close_replica_leases() -> None:
                if self.model_replica_pool is not None:
                    self.model_replica_pool.detach_all()

            if attempt(
                "auto-managed replica lease retirement",
                close_replica_leases,
            ):
                self._auto_model_leases_closed = True

        if not self._fabric_consumer_released:
            attempt(
                "Runtime Fabric consumer release",
                self._release_runtime_fabric_consumer,
            )

        # This runtime owns consumers, not durable physical realizations.
        self._auto_models_removed = True
        self._models_stopped = True

        if not self._operation_runtime_closed:
            if attempt(
                "operation/forensics shutdown",
                self.operation_runtime.close,
            ):
                self._operation_runtime_closed = True

        if not self._observability_closed:
            if attempt(
                "observability shutdown",
                self.observability.close,
            ):
                self._observability_closed = True

        # Dependency order is physical lifetime resources -> Docker I/O group.
        # Pool.close() retires the exact physical owner registry before closing
        # its control domain. Closing this borrowed group first prevents
        # recovery/retirement Docker effects and strands Scope cleanup.
        if not self._pool_closed:
            if attempt(
                "execution-pool shutdown",
                self.execution_pool.close,
            ):
                self._pool_closed = True
                # A converged pool has already closed both owned task groups.
                self._docker_group_closed = True
                self._orchestration_closed = True

        # If another pool owner failed, still attempt independent group
        # retirement to prevent non-daemon workers surviving this request.
        # The failed physical owner remains registered and the final runtime
        # lock remains held: no false claim of converged physical truth.
        if not self._docker_group_closed:
            if attempt(
                "Docker I/O group shutdown",
                lambda: self.execution_pool.close_control_group(
                    self._docker_group,
                    cancel_pending=True,
                ),
            ):
                self._docker_group_closed = True

        if not self._orchestration_closed:
            if attempt(
                "orchestration shutdown",
                lambda: self.execution_pool.close_orchestration_group(
                    self._orchestration_group,
                    cancel_pending=True,
                ),
            ):
                self._orchestration_closed = True

        # The final local lock is an ownership fence, not a cleanup resource.
        # Keep it held when any prior stage failed so another process cannot
        # adopt incompletely converged resources while this process remains live.
        if errors:
            raise BaseExceptionGroup(
                "managed research runtime close failed",
                errors,
            )

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
    resource_competition_policy: ResourceCompetitionPolicy | None = None,
    runtime_fabric_root_path: Path | None = None,
    runtime_consumer_scope: NoetriumUnit = PLATFORM_SCOPE,
    runtime_consumer_scope_lease: NoetriumUnit | None = None,
) -> ManagedResearchRuntime:
    if not isinstance(runtime_consumer_scope, NoetriumUnit):
        raise TypeError("runtime_consumer_scope must be NoetriumUnit")
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
        fabric_layout = _persistence_scoped_layout(
            standard_local_directory_layout(fabric_root / "runtime")
        )
        # Content-addressed asset truth is format-stable and must remain
        # reusable across Unit/Event persistence epochs. Only physical authority
        # state above is schema-scoped.
        durable_fabric_layout = standard_local_directory_layout(
            fabric_root / "content"
        )
        physical_host_identity = LocalLeaseClock().read().host_identity_digest
        host_pressure_observer = LocalHostRuntimeObserver(
            host_id=physical_host_identity
        )
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
        resource_authority = UniversalResourceAuthority(
            fabric_layout.state
            / "platform-resources"
            / "platform-resources.sqlite"
        )
        pool = ResearchExecutionPool(
            resource_authority=resource_authority,
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
            "managed-research-runtime:" + pool.owner_generation_id[:16],
            resource_id="platform-runtime-controller",
            priority=ExecutionPriority.CRITICAL,
        )
        docker_group = pool.open_control_group(
            "managed-research-runtime-docker-io:" + pool.owner_generation_id[:16],
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
                resource_authority=resource_authority,
            )
            # Exact resource graphs reconcile at their realization boundaries.
            # Startup never performs kind-level orphan cleanup because that would
            # destroy warm realizations without exact generation/dependency proof.
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
            management.platform_meta.resource_authority,
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
            _runtime_lock=runtime_lock,
            model_replica_pool=model_replica_pool,
        )
        runtime._attach_runtime_fabric_consumer(
            fabric_layout.locks / "runtime-fabric-consumers.lock",
            holder_scope=runtime_consumer_scope,
            holder_scope_lease=runtime_consumer_scope_lease,
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
