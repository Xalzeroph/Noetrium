from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Condition, RLock
from typing import Callable
from time import time
from uuid import uuid4

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentCatalogPort,
    ModelDeploymentGeneration,
    ModelDeploymentRuntimePort,
    ModelDeploymentSelector,
    ModelDeploymentSpec,
    ModelDeploymentStatus,
    ModelDesiredState,
    ModelFleetRuntimePort,
    ModelRuntimeState,
)
from noetrium_platform.capabilities.model.deployment.runtime.templates import (
    sglang_deployment,
    vllm_deployment,
)
from noetrium_platform.capabilities.model.deployment.runtime.vllm_resources import (
    reconcile_vllm_compute_requirement,
)
from noetrium_platform.capabilities.model.stack.api import ModelStackSpec
from noetrium_platform.capabilities.model.stack.runtime import (
    model_stack_launch_settings,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    ContentAddressedSingleFlight,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability import InterprocessFileLock
from noetrium_platform.infrastructure.resources.lease.api import (
    ResourceIdentity,
    ResourceKind,
    ResourceLeasePort,
)
from noetrium_platform.substrate.api import PLATFORM_SCOPE, ScopeIdentity
from noetrium_platform.substrate.api import (
    EndpointAllocation,
    EndpointAllocationPort,
    EndpointBindingProof,
    EndpointLeaseGuardFactoryPort,
)
from noetrium_platform.substrate.api import (
    ComputeAllocation,
    ComputeBindingProof,
    ComputeLeaseGuardFactoryPort,
    ComputePlacementUnavailable,
    ComputeRequirement,
    ComputeSchedulerPort,
)
from noetrium_platform.substrate.api import ResourceOwnership


_BINDING_CONVERGENCE_ATTEMPTS = 4


class _ModelPlacementCapacityDrift(RuntimeError):
    """A frozen unbound placement lost physical capacity before service binding."""

    def __init__(
        self,
        deployment_id: str,
        compute: ComputeAllocation,
        status: ModelDeploymentStatus,
    ) -> None:
        self.deployment_id = deployment_id
        self.compute = compute
        self.status = status
        super().__init__(
            "model replica placement capacity drifted before binding: "
            f"{deployment_id}: host={compute.host_id} "
            f"gpus={','.join(compute.gpu_ids)} "
            f"status={status.runtime_state.value}:{status.detail}"
        )


def _exception_leaves(error: BaseException) -> tuple[BaseException, ...]:
    """Return root failures without losing causal multiplicity."""
    if isinstance(error, BaseExceptionGroup):
        leaves: list[BaseException] = []
        for child in error.exceptions:
            leaves.extend(_exception_leaves(child))
        return tuple(leaves)
    return (error,)


def _converge_running_replica_bindings(
    *,
    deployment_runtime: ModelDeploymentRuntimePort,
    compute_scheduler: ComputeSchedulerPort,
    endpoint_allocations: EndpointAllocationPort,
    deployment_id: str,
    expected_desired_spec_digest: str,
    compute: ComputeAllocation,
    endpoint: EndpointAllocation,
) -> tuple[
    ComputeAllocation,
    EndpointAllocation,
    ModelDeploymentGeneration,
    ModelDeploymentStatus,
]:
    """Converge resource proofs onto one stable running runtime generation.

    Model status and generation are separate authority reads. A process can restart
    between them, so a RUNNING observation must never be attached to a different
    applied generation. We use an optimistic stable-read window around status,
    CAS-rebind both physical-resource proofs, then verify the runtime generation
    once more after both authorities committed. Continuous churn fails closed.
    """

    current_compute = compute
    current_endpoint = endpoint
    for _attempt in range(_BINDING_CONVERGENCE_ATTEMPTS):
        before = deployment_runtime.generation(deployment_id)
        if before.desired_spec_digest != expected_desired_spec_digest:
            raise RuntimeError(
                "model replica desired generation drifted before physical binding: "
                f"{deployment_id}"
            )
        status = deployment_runtime.status(deployment_id)
        after = deployment_runtime.generation(deployment_id)
        if after.desired_spec_digest != expected_desired_spec_digest:
            raise RuntimeError(
                "model replica desired generation drifted during physical binding: "
                f"{deployment_id}"
            )
        if before != after:
            continue
        if status.runtime_state is not ModelRuntimeState.RUNNING:
            raise RuntimeError(
                f"model replica is not running: {deployment_id}: "
                f"{status.runtime_state.value}:{status.detail}"
            )
        applied = after.applied_runtime_digest
        if applied is None:
            raise RuntimeError(
                "running model replica has no applied runtime generation: "
                f"{deployment_id}"
            )

        observed_at = time()
        base_evidence = status.detail or f"model-ready:{deployment_id}"
        evidence_ref = f"{base_evidence};runtime-generation:{applied}"

        if current_compute.binding_binder_identity_digest != applied:
            compute_proof = ComputeBindingProof(
                allocation_id=current_compute.allocation_id,
                host_id=current_compute.host_id,
                gpu_ids=current_compute.gpu_ids,
                lease_fencing_token=current_compute.lease_fencing_token,
                binder_identity_digest=applied,
                observed_at_epoch_s=observed_at,
                evidence_ref=evidence_ref,
            )
            if current_compute.binding_proof_digest is None:
                current_compute = compute_scheduler.confirm_bound(compute_proof)
            else:
                current_compute = compute_scheduler.replace_bound(
                    compute_proof,
                    previous_binding_proof_digest=(
                        current_compute.binding_proof_digest
                    ),
                )

        if current_endpoint.binding_binder_identity_digest != applied:
            endpoint_proof = EndpointBindingProof(
                allocation_id=current_endpoint.allocation_id,
                endpoint=current_endpoint.endpoint,
                lease_fencing_token=current_endpoint.lease_fencing_token,
                binder_identity_digest=applied,
                observed_at_epoch_s=observed_at,
                evidence_ref=evidence_ref,
            )
            if current_endpoint.binding_proof_digest is None:
                current_endpoint = endpoint_allocations.confirm_bound(
                    endpoint_proof
                )
            else:
                current_endpoint = endpoint_allocations.replace_bound(
                    endpoint_proof,
                    expected_previous_binding_proof_digest=(
                        current_endpoint.binding_proof_digest
                    ),
                )

        final = deployment_runtime.generation(deployment_id)
        if final.desired_spec_digest != expected_desired_spec_digest:
            raise RuntimeError(
                "model replica desired generation drifted after physical binding: "
                f"{deployment_id}"
            )
        if final == after:
            if (
                current_compute.binding_binder_identity_digest != applied
                or current_endpoint.binding_binder_identity_digest != applied
            ):
                raise RuntimeError(
                    "model replica physical resource bindings did not converge: "
                    f"{deployment_id}"
                )
            return current_compute, current_endpoint, after, status

    raise RuntimeError(
        "model replica runtime generation did not stabilize during physical binding: "
        f"{deployment_id}"
    )


@dataclass(frozen=True, slots=True)
class ModelReplicaPoolRequest:
    """High-level desired model fleet without concrete GPU or port identity."""

    pool_id: str
    scope: ScopeIdentity
    model_id: str
    engine: str
    cwd: Path
    compute: ComputeRequirement
    model_stack: ModelStackSpec
    replica_count: int | None = None
    endpoint_host: str = "127.0.0.1"
    endpoint_candidate_count: int = 32
    extra_args: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.pool_id, "pool_id"),
            (self.model_id, "model_id"),
            (self.engine, "engine"),
            (self.endpoint_host, "endpoint_host"),
        ):
            if not value.strip():
                raise ValueError(f"model replica pool {field_name} is required")
        if self.engine not in {"vllm", "sglang"}:
            raise ValueError("model replica pool supports vllm or sglang")
        if self.compute.gpu_count <= 0:
            raise ValueError("automatic model replica pools currently require GPU resources")
        if not isinstance(self.model_stack, ModelStackSpec):
            raise TypeError("model replica pool model_stack must be ModelStackSpec")
        if self.model_stack.identity.model_id != self.model_id:
            raise ValueError("model replica pool model_id must match frozen model stack")
        if self.model_stack.identity.engine.lower() != self.engine:
            raise ValueError("model replica pool engine must match frozen model stack")
        if self.extra_args:
            raise ValueError(
                "model replica pool extra_args are forbidden; "
                "put engine arguments in ModelStackSpec.engine_args"
            )
        if self.engine == "vllm":
            if self.model_stack.data_parallel != 1:
                raise ValueError(
                    "automatic vLLM replica pools use independent replicas; "
                    "internal data_parallel requires an auxiliary RPC endpoint "
                    "with its own binding/recovery authority"
                )
            required_gpus = (
                self.model_stack.tensor_parallel
                * self.model_stack.pipeline_parallel
            )
        else:
            if (
                self.model_stack.data_parallel != 1
                or self.model_stack.pipeline_parallel != 1
            ):
                raise ValueError(
                    "automatic SGLang replica pools currently support tensor parallel only"
                )
            required_gpus = self.model_stack.tensor_parallel
        if self.compute.gpu_count != required_gpus:
                raise ValueError(
                    "model replica pool compute.gpu_count must match frozen engine topology"
                )
        if self.replica_count is not None and (
            type(self.replica_count) is not int or self.replica_count <= 0
        ):
            raise ValueError("replica_count must be positive when provided")
        if type(self.endpoint_candidate_count) is not int or self.endpoint_candidate_count <= 0:
            raise ValueError("endpoint_candidate_count must be positive")

    @property
    def effective_compute(self) -> ComputeRequirement:
        if self.engine != "vllm":
            return self.compute
        return reconcile_vllm_compute_requirement(
            self.model_stack,
            self.compute,
        )

    @property
    def runtime_identity_digest(self) -> str:
        """Physical serving identity; paper/run labels never split a warm runtime."""
        return canonical_digest(
            {
                "schema": "noetrium.model-replica-runtime-identity.v1",
                "scope": self.scope,
                "model_id": self.model_id,
                "engine": self.engine,
                "cwd": str(self.cwd.expanduser().resolve()),
                "compute": self.effective_compute,
                "model_stack_digest": self.model_stack.digest(),
                "replica_count": self.replica_count,
                "endpoint_host": self.endpoint_host,
            }
        )


@dataclass(frozen=True, slots=True)
class ModelReplicaPlacement:
    replica_index: int
    deployment_id: str
    compute: ComputeAllocation
    endpoint: EndpointAllocation
    deployment: ModelDeploymentSpec
    generation: ModelDeploymentGeneration
    status: ModelDeploymentStatus

    @property
    def placement_digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ModelReplicaPoolReport:
    request_digest: str
    placement_generation_id: str
    placements: tuple[ModelReplicaPlacement, ...]
    report_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.placement_generation_id) is not str
            or len(self.placement_generation_id) != 32
            or any(
                character not in "0123456789abcdef"
                for character in self.placement_generation_id
            )
        ):
            raise ValueError(
                "model replica pool placement_generation_id must be uuid4 hex"
            )
        if not self.placements:
            raise ValueError("model replica pool report requires placements")
        if len({row.deployment_id for row in self.placements}) != len(self.placements):
            raise ValueError("model replica pool deployment ids must be unique")
        object.__setattr__(
            self,
            "report_digest",
            canonical_digest(
                {
                    "request_digest": self.request_digest,
                    "placement_generation_id": self.placement_generation_id,
                    "placements": tuple(row.placement_digest for row in self.placements),
                }
            ),
        )


class _ModelReplicaPoolOwner:
    """Own one warm physical model realization and all resource heartbeats."""

    def __init__(
        self,
        report: ModelReplicaPoolReport,
        *,
        deployment_runtime: ModelDeploymentRuntimePort,
        compute_scheduler: ComputeSchedulerPort,
        endpoint_allocations: EndpointAllocationPort,
        compute_guard,
        endpoint_guard,
    ) -> None:
        self.report = report
        self._deployment_runtime = deployment_runtime
        self._compute_scheduler = compute_scheduler
        self._endpoint_allocations = endpoint_allocations
        self._compute_guard = compute_guard
        self._endpoint_guard = endpoint_guard
        self._removed_deployment_ids: set[str] = set()
        self._endpoint_guard_closed = False
        self._compute_guard_closed = False
        self._released_endpoint_ids: set[str] = set()
        self._released_compute_ids: set[str] = set()
        self._current_generations = {
            row.deployment_id: row.generation for row in report.placements
        }
        self._current_compute = {
            row.compute.allocation_id: row.compute for row in report.placements
        }
        self._current_endpoints = {
            row.endpoint.allocation_id: row.endpoint for row in report.placements
        }
        self._closed = False
        self._lifecycle_lock = RLock()

    @property
    def closed(self) -> bool:
        with self._lifecycle_lock:
            return self._closed

    def _current_generation(
        self,
        row: ModelReplicaPlacement,
    ) -> ModelDeploymentGeneration:
        generation = self._deployment_runtime.generation(row.deployment_id)
        if generation.desired_spec_digest != row.generation.desired_spec_digest:
            raise RuntimeError(
                "model replica desired generation drifted: "
                f"{row.deployment_id}"
            )
        return generation

    def _converge_running_generation(
        self,
        row: ModelReplicaPlacement,
    ) -> None:
        compute = self._current_compute[row.compute.allocation_id]
        endpoint = self._current_endpoints[row.endpoint.allocation_id]
        compute, endpoint, generation, _status = _converge_running_replica_bindings(
            deployment_runtime=self._deployment_runtime,
            compute_scheduler=self._compute_scheduler,
            endpoint_allocations=self._endpoint_allocations,
            deployment_id=row.deployment_id,
            expected_desired_spec_digest=row.generation.desired_spec_digest,
            compute=compute,
            endpoint=endpoint,
        )
        self._current_compute[compute.allocation_id] = compute
        self._current_endpoints[endpoint.allocation_id] = endpoint
        self._current_generations[row.deployment_id] = generation

    def assert_healthy(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("model replica physical owner is closed")
            self._compute_guard.assert_healthy()
            self._endpoint_guard.assert_healthy()
            for row in self.report.placements:
                self._converge_running_generation(row)

    def detach(self) -> None:
        """Stop this controller's heartbeats without retiring the realization."""
        with self._lifecycle_lock:
            if self._closed:
                return
            errors: list[BaseException] = []
            if not self._endpoint_guard_closed:
                try:
                    self._endpoint_guard.close()
                except BaseException as exc:
                    errors.extend(_exception_leaves(exc))
                else:
                    self._endpoint_guard_closed = True
            if not self._compute_guard_closed:
                try:
                    self._compute_guard.close()
                except BaseException as exc:
                    errors.extend(_exception_leaves(exc))
                else:
                    self._compute_guard_closed = True
            if errors:
                raise BaseExceptionGroup(
                    "model replica physical owner detach failed",
                    errors,
                )
            self._closed = True

    def close(self) -> None:
        with self._lifecycle_lock:
            self._close_locked()

    def _close_locked(self) -> None:
        if self._closed:
            return
        errors: list[BaseException] = []
        for row in reversed(self.report.placements):
            if row.deployment_id in self._removed_deployment_ids:
                continue
            try:
                generation = self._current_generation(row)
                self._deployment_runtime.remove_deployment(generation)
            except BaseException as exc:
                errors.extend(_exception_leaves(exc))
            else:
                self._current_generations[row.deployment_id] = generation
                self._removed_deployment_ids.add(row.deployment_id)
        if len(self._removed_deployment_ids) != len(self.report.placements):
            raise BaseExceptionGroup("model replica pool cleanup failed", errors)
        if not self._endpoint_guard_closed:
            try:
                self._endpoint_guard.close()
            except BaseException as exc:
                errors.extend(_exception_leaves(exc))
            else:
                self._endpoint_guard_closed = True
        if not self._compute_guard_closed:
            try:
                self._compute_guard.close()
            except BaseException as exc:
                errors.extend(_exception_leaves(exc))
            else:
                self._compute_guard_closed = True
        if self._endpoint_guard_closed:
            for row in reversed(self.report.placements):
                allocation_id = row.endpoint.allocation_id
                if allocation_id in self._released_endpoint_ids:
                    continue
                try:
                    self._endpoint_allocations.release(
                        self._current_endpoints[allocation_id]
                    )
                except BaseException as exc:
                    errors.extend(_exception_leaves(exc))
                else:
                    self._released_endpoint_ids.add(allocation_id)
        if self._compute_guard_closed:
            for row in reversed(self.report.placements):
                allocation_id = row.compute.allocation_id
                if allocation_id in self._released_compute_ids:
                    continue
                try:
                    self._compute_scheduler.release(
                        self._current_compute[allocation_id]
                    )
                except BaseException as exc:
                    errors.extend(_exception_leaves(exc))
                else:
                    self._released_compute_ids.add(allocation_id)
        if errors:
            raise BaseExceptionGroup("model replica pool cleanup failed", errors)
        self._closed = (
            self._endpoint_guard_closed
            and self._compute_guard_closed
            and len(self._released_endpoint_ids) == len(self.report.placements)
            and len(self._released_compute_ids) == len(self.report.placements)
        )
        if not self._closed:
            raise RuntimeError("model replica pool cleanup did not converge")


class ModelReplicaPoolLease:
    """Lightweight consumer lease for one warm physical model realization."""

    def __init__(
        self,
        owner: _ModelReplicaPoolOwner,
        *,
        consumer_lease_id: str,
        on_closed: Callable[["ModelReplicaPoolLease"], None],
    ) -> None:
        if not consumer_lease_id:
            raise ValueError("model replica consumer lease id is required")
        self.report = owner.report
        self.consumer_lease_id = consumer_lease_id
        self._owner = owner
        self._on_closed = on_closed
        self._closed = False
        self._lifecycle_lock = RLock()

    @property
    def closed(self) -> bool:
        with self._lifecycle_lock:
            return self._closed

    def assert_healthy(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("model replica consumer lease is closed")
            self._owner.assert_healthy()

    def close(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
        self._on_closed(self)

    def __enter__(self) -> "ModelReplicaPoolLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


class _PendingModelReplicaCleanup:
    """Retryable owner for a failed replica-pool construction generation."""

    def __init__(
        self,
        *,
        cleanup_id: str,
        specs: tuple[ModelDeploymentSpec, ...],
        compute_rows: tuple[ComputeAllocation, ...],
        endpoint_rows: tuple[EndpointAllocation, ...],
        deployment_runtime: ModelDeploymentRuntimePort,
        compute_scheduler: ComputeSchedulerPort,
        endpoint_allocations: EndpointAllocationPort,
        compute_guard,
        endpoint_guard,
    ) -> None:
        self.cleanup_id = cleanup_id
        self._specs = specs
        self._compute_rows = compute_rows
        self._endpoint_rows = endpoint_rows
        self._deployment_runtime = deployment_runtime
        self._compute_scheduler = compute_scheduler
        self._endpoint_allocations = endpoint_allocations
        self._compute_guard = compute_guard
        self._endpoint_guard = endpoint_guard
        self._removed_deployment_ids: set[str] = set()
        self._endpoint_guard_closed = endpoint_guard is None
        self._compute_guard_closed = compute_guard is None
        self._released_endpoint_ids: set[str] = set()
        self._released_compute_ids: set[str] = set()
        self._closed = False
        self._lock = RLock()

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            errors: list[BaseException] = []

            for spec in reversed(self._specs):
                if spec.deployment_id in self._removed_deployment_ids:
                    continue
                try:
                    generation = self._deployment_runtime.generation(
                        spec.deployment_id
                    )
                    if generation.desired_spec_digest != canonical_digest(spec):
                        raise RuntimeError(
                            "model replica cleanup lost desired generation authority: "
                            f"{spec.deployment_id}"
                        )
                    self._deployment_runtime.remove_deployment(generation)
                except KeyError:
                    # No desired/applied generation remains: physical service
                    # ownership is already converged for this identity.
                    self._removed_deployment_ids.add(spec.deployment_id)
                except BaseException as exc:
                    errors.extend(_exception_leaves(exc))
                else:
                    self._removed_deployment_ids.add(spec.deployment_id)

            deployments_removed = (
                len(self._removed_deployment_ids) == len(self._specs)
            )
            if not deployments_removed:
                raise BaseExceptionGroup(
                    "pending model replica cleanup did not stop all deployments",
                    errors,
                )

            if not self._endpoint_guard_closed:
                try:
                    self._endpoint_guard.close()
                except BaseException as exc:
                    errors.extend(_exception_leaves(exc))
                else:
                    self._endpoint_guard_closed = True
            if not self._compute_guard_closed:
                try:
                    self._compute_guard.close()
                except BaseException as exc:
                    errors.extend(_exception_leaves(exc))
                else:
                    self._compute_guard_closed = True

            if self._endpoint_guard_closed:
                for endpoint in reversed(self._endpoint_rows):
                    if endpoint.allocation_id in self._released_endpoint_ids:
                        continue
                    try:
                        self._endpoint_allocations.release(endpoint)
                    except BaseException as exc:
                        errors.extend(_exception_leaves(exc))
                    else:
                        self._released_endpoint_ids.add(endpoint.allocation_id)

            if self._compute_guard_closed:
                for compute in reversed(self._compute_rows):
                    if compute.allocation_id in self._released_compute_ids:
                        continue
                    try:
                        self._compute_scheduler.release(compute)
                    except BaseException as exc:
                        errors.extend(_exception_leaves(exc))
                    else:
                        self._released_compute_ids.add(compute.allocation_id)

            if errors:
                raise BaseExceptionGroup(
                    "pending model replica cleanup failed",
                    errors,
                )

            self._closed = (
                self._endpoint_guard_closed
                and self._compute_guard_closed
                and len(self._released_endpoint_ids) == len(self._endpoint_rows)
                and len(self._released_compute_ids) == len(self._compute_rows)
            )
            if not self._closed:
                raise RuntimeError(
                    "pending model replica cleanup did not converge"
                )


class LocalModelReplicaPoolRuntime:
    """One warm physical model fabric with lightweight consumer leases."""

    def __init__(
        self,
        *,
        deployment_catalog: ModelDeploymentCatalogPort,
        deployment_runtime: ModelDeploymentRuntimePort,
        fleet: ModelFleetRuntimePort,
        compute_scheduler: ComputeSchedulerPort,
        endpoint_allocations: EndpointAllocationPort,
        compute_lease_guards: ComputeLeaseGuardFactoryPort,
        endpoint_lease_guards: EndpointLeaseGuardFactoryPort,
        realization_singleflight: ContentAddressedSingleFlight | None = None,
        runtime_fabric_leases: ResourceLeasePort | None = None,
        runtime_fabric_consumer_lease_id: str | None = None,
        runtime_fabric_consumer_lock_path: Path | None = None,
    ) -> None:
        self._catalog = deployment_catalog
        self._deployment_runtime = deployment_runtime
        self._fleet = fleet
        self._compute_scheduler = compute_scheduler
        self._endpoint_allocations = endpoint_allocations
        self._compute_lease_guards = compute_lease_guards
        self._endpoint_lease_guards = endpoint_lease_guards
        self._realization_singleflight = realization_singleflight
        pressure_authority = (
            runtime_fabric_leases,
            runtime_fabric_consumer_lease_id,
            runtime_fabric_consumer_lock_path,
        )
        if any(value is not None for value in pressure_authority) and any(
            value is None for value in pressure_authority
        ):
            raise ValueError(
                "model pressure reclaim requires leases, consumer identity and coordination lock"
            )
        if (
            runtime_fabric_consumer_lease_id is not None
            and not runtime_fabric_consumer_lease_id.strip()
        ):
            raise ValueError("runtime fabric consumer lease id must be non-empty")
        self._runtime_fabric_leases = runtime_fabric_leases
        self._runtime_fabric_consumer_lease_id = runtime_fabric_consumer_lease_id
        self._runtime_fabric_consumer_lock_path = runtime_fabric_consumer_lock_path
        self._lifecycle_lock = RLock()
        self._lifecycle_changed = Condition(self._lifecycle_lock)
        self._realization_locks: dict[str, RLock] = {}
        self._materializations_in_flight = 0
        self._owners_by_runtime_identity: dict[str, _ModelReplicaPoolOwner] = {}
        self._active_leases: dict[str, ModelReplicaPoolLease] = {}
        self._pending_cleanups: dict[str, _PendingModelReplicaCleanup] = {}
        self._closing = False
        self._closed = False

    @property
    def active_lease_count(self) -> int:
        with self._lifecycle_lock:
            return len(self._active_leases)

    @property
    def warm_owner_count(self) -> int:
        with self._lifecycle_lock:
            return len(self._owners_by_runtime_identity)

    @property
    def pending_cleanup_count(self) -> int:
        with self._lifecycle_lock:
            return len(self._pending_cleanups)

    def _retry_pending_cleanups_locked(self) -> None:
        errors: list[BaseException] = []
        for cleanup_id, cleanup in tuple(self._pending_cleanups.items()):
            try:
                cleanup.close()
            except BaseException as exc:
                errors.extend(_exception_leaves(exc))
            else:
                self._pending_cleanups.pop(cleanup_id, None)
        if errors:
            raise BaseExceptionGroup(
                "model replica pool pending cleanup failed",
                errors,
            )

    def _lease_closed(self, lease: ModelReplicaPoolLease) -> None:
        with self._lifecycle_lock:
            current = self._active_leases.get(lease.consumer_lease_id)
            if current is lease:
                self._active_leases.pop(lease.consumer_lease_id, None)

    def _realization_lock(self, identity: str) -> RLock:
        with self._lifecycle_lock:
            lock = self._realization_locks.get(identity)
            if lock is None:
                lock = RLock()
                self._realization_locks[identity] = lock
            return lock

    def _wait_for_materializations_locked(self) -> None:
        while self._materializations_in_flight:
            self._lifecycle_changed.wait()

    def _consumer_locked(
        self,
        owner: _ModelReplicaPoolOwner,
    ) -> ModelReplicaPoolLease:
        consumer_lease_id = uuid4().hex
        lease = ModelReplicaPoolLease(
            owner,
            consumer_lease_id=consumer_lease_id,
            on_closed=self._lease_closed,
        )
        self._active_leases[consumer_lease_id] = lease
        return lease

    def detach_all(self) -> None:
        """Detach this controller while preserving durable warm realizations."""
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closing = True
            self._wait_for_materializations_locked()
            errors: list[BaseException] = []
            for lease in tuple(self._active_leases.values()):
                try:
                    lease.close()
                except BaseException as exc:
                    errors.extend(_exception_leaves(exc))
            for identity, owner in tuple(
                self._owners_by_runtime_identity.items()
            ):
                try:
                    owner.detach()
                except BaseException as exc:
                    errors.extend(_exception_leaves(exc))
                else:
                    self._owners_by_runtime_identity.pop(identity, None)
            try:
                self._retry_pending_cleanups_locked()
            except BaseException as exc:
                errors.extend(_exception_leaves(exc))
            if errors:
                raise BaseExceptionGroup(
                    "model replica pool runtime detach failed",
                    errors,
                )
            if self._active_leases or self._owners_by_runtime_identity:
                raise RuntimeError(
                    "model replica pool detach did not release controller ownership"
                )
            self._closed = True

    def close_all(self) -> None:
        """Retire consumers first, then the physical runtime fabric."""
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closing = True
            self._wait_for_materializations_locked()
            errors: list[BaseException] = []
            for lease in tuple(self._active_leases.values()):
                try:
                    lease.close()
                except BaseException as exc:
                    errors.extend(_exception_leaves(exc))
            for identity, owner in tuple(
                self._owners_by_runtime_identity.items()
            ):
                try:
                    owner.close()
                except BaseException as exc:
                    errors.extend(_exception_leaves(exc))
                else:
                    self._owners_by_runtime_identity.pop(identity, None)
            try:
                self._retry_pending_cleanups_locked()
            except BaseException as exc:
                errors.extend(_exception_leaves(exc))
            if errors:
                raise BaseExceptionGroup(
                    "model replica pool runtime cleanup failed",
                    errors,
                )
            if (
                self._active_leases
                or self._owners_by_runtime_identity
                or self._pending_cleanups
            ):
                raise RuntimeError(
                    "model replica pool runtime cleanup did not retire all ownership"
                )
            self._closed = True

    def retire(self, request: ModelReplicaPoolRequest) -> bool:
        """Retire one exact warm realization when it has no active consumers."""
        if not isinstance(request, ModelReplicaPoolRequest):
            raise TypeError("model replica retirement requires ModelReplicaPoolRequest")
        identity = request.runtime_identity_digest
        realization_lock = self._realization_lock(identity)
        with realization_lock:
            with self._lifecycle_lock:
                if self._closed:
                    raise RuntimeError("model replica pool runtime is closed")
                if self._closing:
                    raise RuntimeError("model replica pool runtime is closing")
                self._retry_pending_cleanups_locked()
                owner = self._owners_by_runtime_identity.get(identity)
                if owner is None:
                    return False
                consumers = tuple(
                    lease.consumer_lease_id
                    for lease in self._active_leases.values()
                    if lease._owner is owner and not lease.closed
                )
                if consumers:
                    raise RuntimeError(
                        "cannot retire model realization with active consumers: "
                        + ",".join(sorted(consumers))
                    )
                owner.close()
                current = self._owners_by_runtime_identity.get(identity)
                if current is not owner:
                    raise RuntimeError(
                        "model realization owner changed during retirement"
                    )
                self._owners_by_runtime_identity.pop(identity, None)
                return True

    def _pressure_reclaim_has_exclusive_runtime_fabric_consumer(self) -> bool:
        leases = self._runtime_fabric_leases
        own_lease_id = self._runtime_fabric_consumer_lease_id
        if leases is None or own_lease_id is None:
            return False
        active = leases.active_for(
            ResourceIdentity(ResourceKind.RUNTIME_FABRIC, "host-runtime-fabric")
        )
        own = tuple(row for row in active if row.lease_id == own_lease_id)
        if len(own) != 1:
            return False
        return all(row.lease_id == own_lease_id for row in active)

    def reclaim_one_stale_warm_realization(
        self,
        *,
        protected_runtime_identities: frozenset[str] = frozenset(),
    ) -> str | None:
        """Pressure-evict one globally idle durable realization.

        The host Runtime Fabric consumer lock makes the zero-foreign-consumer
        proof atomic with physical retirement. Per-realization single-flight
        then excludes concurrent adoption of the exact warm model while its
        expired compute/endpoint generations are stopped and recovered.
        """
        if type(protected_runtime_identities) is not frozenset or any(
            type(value) is not str for value in protected_runtime_identities
        ):
            raise TypeError("protected model runtime identities must be frozenset[str]")
        lock_path = self._runtime_fabric_consumer_lock_path
        if (
            lock_path is None
            or self._runtime_fabric_leases is None
            or self._runtime_fabric_consumer_lease_id is None
        ):
            return None
        singleflight = self._realization_singleflight
        if singleflight is None:
            raise RuntimeError(
                "model pressure reclaim requires global realization single-flight"
            )

        with InterprocessFileLock(lock_path):
            if not self._pressure_reclaim_has_exclusive_runtime_fabric_consumer():
                return None
            with self._lifecycle_lock:
                if self._closed:
                    raise RuntimeError("model replica pool runtime is closed")
                if self._closing:
                    raise RuntimeError("model replica pool runtime is closing")
                locally_owned = frozenset(self._owners_by_runtime_identity)

            now_epoch_s = time()
            compute_by_id = {
                row.allocation_id: row
                for row in self._compute_scheduler.allocations()
            }
            groups: dict[str, list[ModelDeploymentSpec]] = {}
            for spec in self._catalog.select(
                ModelDeploymentSelector(tags=("auto-managed",))
            ):
                identity = self._runtime_identity(spec)
                if identity in protected_runtime_identities or identity in locally_owned:
                    continue
                groups.setdefault(identity, []).append(spec)

            candidates: list[
                tuple[
                    float,
                    int,
                    str,
                    tuple[ModelDeploymentSpec, ...],
                    tuple[ComputeAllocation, ...],
                ]
            ] = []
            for identity, raw_specs in groups.items():
                specs = tuple(sorted(raw_specs, key=lambda row: row.deployment_id))
                generation_ids = {
                    self._placement_generation_id(spec) for spec in specs
                }
                if len(generation_ids) != 1:
                    continue
                placement_generation_id = next(iter(generation_ids))
                compute_rows: list[ComputeAllocation] = []
                valid = True
                for spec in specs:
                    index = self._replica_index(spec)
                    allocation_id = (
                        f"model-realization:{identity}:"
                        f"{placement_generation_id}:{index}:compute"
                    )
                    row = compute_by_id.get(allocation_id)
                    if (
                        row is None
                        or row.lease_expires_at_epoch_s is None
                        or row.lease_expires_at_epoch_s > now_epoch_s
                    ):
                        valid = False
                        break
                    compute_rows.append(row)
                if not valid or not compute_rows:
                    continue
                last_owned_at = max(
                    float(row.lease_expires_at_epoch_s or 0.0)
                    for row in compute_rows
                )
                reserved_vram = sum(
                    sum(row.gpu_memory_reservation_bytes) for row in compute_rows
                )
                candidates.append(
                    (
                        last_owned_at,
                        -reserved_vram,
                        identity,
                        specs,
                        tuple(compute_rows),
                    )
                )

            if not candidates:
                return None
            _expired_at, _negative_vram, identity, _specs, _compute = min(
                candidates
            )
            realization_lock = self._realization_lock(identity)
            with realization_lock, singleflight.producer("model-realization", identity):
                # A local consumer may have appeared while this realization
                # waited for its cross-process producer fence.
                with self._lifecycle_lock:
                    owner = self._owners_by_runtime_identity.get(identity)
                    if owner is not None:
                        if any(
                            lease._owner is owner and not lease.closed
                            for lease in self._active_leases.values()
                        ):
                            return None
                        owner.close()
                        self._owners_by_runtime_identity.pop(identity, None)
                        return identity

                # Re-read every durable authority after acquiring both fences.
                specs = tuple(
                    sorted(
                        self._catalog.select(
                            ModelDeploymentSelector(
                                tags=(f"runtime-identity:{identity}",),
                            )
                        ),
                        key=lambda row: row.deployment_id,
                    )
                )
                if not specs:
                    return None
                generation_ids = {
                    self._placement_generation_id(spec) for spec in specs
                }
                if len(generation_ids) != 1:
                    raise RuntimeError(
                        "stale warm realization spans multiple placement generations: "
                        + identity
                    )
                placement_generation_id = next(iter(generation_ids))
                current_compute = {
                    row.allocation_id: row
                    for row in self._compute_scheduler.allocations()
                }
                compute_rows: list[ComputeAllocation] = []
                endpoint_rows: list[EndpointAllocation] = []
                generations: list[ModelDeploymentGeneration] = []
                for spec in specs:
                    index = self._replica_index(spec)
                    compute_id = (
                        f"model-realization:{identity}:"
                        f"{placement_generation_id}:{index}:compute"
                    )
                    endpoint_id = (
                        f"model-realization:{identity}:"
                        f"{placement_generation_id}:{index}:endpoint"
                    )
                    compute = current_compute.get(compute_id)
                    endpoint = self._endpoint_allocations.get(endpoint_id)
                    if compute is None or endpoint is None:
                        raise RuntimeError(
                            "stale warm realization lost deterministic allocation: "
                            + spec.deployment_id
                        )
                    if (
                        compute.lease_expires_at_epoch_s is None
                        or compute.lease_expires_at_epoch_s > now_epoch_s
                        or endpoint.lease_expires_at_epoch_s is None
                        or endpoint.lease_expires_at_epoch_s > now_epoch_s
                    ):
                        return None
                    compute_rows.append(compute)
                    endpoint_rows.append(endpoint)
                    generations.append(
                        self._deployment_runtime.generation(spec.deployment_id)
                    )

                # Stop physical binders before retiring their lower resource
                # generations. Recovery release is valid only after that proof.
                for generation in reversed(generations):
                    self._deployment_runtime.remove_deployment(generation)
                errors: list[BaseException] = []
                for endpoint in reversed(endpoint_rows):
                    try:
                        self._endpoint_allocations.recover_release(
                            endpoint, now=now_epoch_s
                        )
                    except BaseException as exc:
                        errors.extend(_exception_leaves(exc))
                for compute in reversed(compute_rows):
                    try:
                        self._compute_scheduler.recover_release(compute)
                    except BaseException as exc:
                        errors.extend(_exception_leaves(exc))
                if errors:
                    raise BaseExceptionGroup(
                        "stale warm model pressure reclaim failed",
                        errors,
                    )
                return identity

    def _target_count(self, request: ModelReplicaPoolRequest) -> int | None:
        if request.replica_count is not None:
            return request.replica_count
        compute = request.effective_compute
        if not self._compute_scheduler.candidates(
            compute,
            scope=request.scope,
        ):
            raise RuntimeError(
                "no automatic model replica capacity is currently available"
            )
        # Automatic mode is work-conserving: do not infer capacity from GPU
        # cardinality because shareable GPUs may host multiple independently
        # fenced replicas. The scheduler is the physical-capacity authority.
        return None

    @staticmethod
    def _deployment(
        request: ModelReplicaPoolRequest,
        *,
        replica_index: int,
        placement_generation_id: str,
        endpoint: EndpointAllocation,
        compute: ComputeAllocation,
    ) -> ModelDeploymentSpec:
        deployment_id = (
            f"model-realization-{request.runtime_identity_digest[:24]}"
            f"-generation-{placement_generation_id[:16]}"
            f"-replica-{replica_index:03d}"
        )
        stack = request.model_stack
        launch_settings = model_stack_launch_settings(stack)
        engine_args = launch_settings.engine_args
        stack_environment = launch_settings.environment
        tensor_parallel = stack.tensor_parallel
        common = dict(
            deployment_id=deployment_id,
            scope=request.scope,
            model_id=request.model_id,
            container_digest=stack.runtime.container_digest,
            cwd=request.cwd,
            host=endpoint.endpoint.host,
            port=endpoint.endpoint.port,
            tensor_parallel=tensor_parallel,
            gpu_devices=compute.gpu_ids,
            gpu_memory_reservation_bytes=compute.gpu_memory_reservation_bytes,
            extra_args=engine_args,
        )
        if request.engine == "vllm":
            spec = vllm_deployment(
                **common,
                data_parallel=1,
                pipeline_parallel=stack.pipeline_parallel,
            )
        elif request.engine == "sglang":
            spec = sglang_deployment(**common)
        else:
            raise AssertionError(request.engine)
        tags = tuple(sorted({
            "auto-managed",
            f"placement-generation:{placement_generation_id}",
            f"replica-index:{replica_index:03d}",
            f"model-stack:{stack.digest()}",
            f"runtime-identity:{request.runtime_identity_digest}",
        }))
        from dataclasses import replace
        return replace(
            spec,
            environment=tuple(sorted((*spec.environment, *stack_environment))),
            desired_state=ModelDesiredState.RUNNING,
            tags=tags,
        )

    @staticmethod
    def _runtime_identity(spec: ModelDeploymentSpec) -> str:
        values = tuple(
            tag.removeprefix("runtime-identity:")
            for tag in spec.tags
            if tag.startswith("runtime-identity:")
        )
        if len(values) != 1:
            raise RuntimeError(
                "model realization requires one runtime-identity tag: "
                f"{spec.deployment_id}"
            )
        value = values[0]
        if (
            len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise RuntimeError(
                "model realization runtime identity is invalid: "
                f"{spec.deployment_id}"
            )
        return value

    @staticmethod
    def _replica_index(spec: ModelDeploymentSpec) -> int:
        values = tuple(
            tag.removeprefix("replica-index:")
            for tag in spec.tags
            if tag.startswith("replica-index:")
        )
        if len(values) != 1 or not values[0].isdigit():
            raise RuntimeError(
                "model realization requires one canonical replica-index tag: "
                f"{spec.deployment_id}"
            )
        value = int(values[0])
        if values[0] != f"{value:03d}":
            raise RuntimeError(
                "model realization replica index is not canonical: "
                f"{spec.deployment_id}"
            )
        return value

    @staticmethod
    def _placement_generation_id(spec: ModelDeploymentSpec) -> str:
        values = tuple(
            tag.removeprefix("placement-generation:")
            for tag in spec.tags
            if tag.startswith("placement-generation:")
        )
        if len(values) != 1:
            raise RuntimeError(
                "model realization requires one placement-generation tag: "
                f"{spec.deployment_id}"
            )
        value = values[0]
        if (
            len(value) != 32
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise RuntimeError(
                "model realization placement generation is invalid: "
                f"{spec.deployment_id}"
            )
        return value

    def _adopt_durable_owner_locked(
        self,
        request: ModelReplicaPoolRequest,
    ) -> _ModelReplicaPoolOwner | None:
        identity = request.runtime_identity_digest
        specs = tuple(
            sorted(
                self._catalog.select(
                    ModelDeploymentSelector(
                        tags=(f"runtime-identity:{identity}",),
                    )
                ),
                key=lambda row: row.deployment_id,
            )
        )
        if not specs:
            return None
        if request.replica_count is not None and len(specs) != request.replica_count:
            raise RuntimeError(
                "durable model realization replica count drifted: "
                f"{identity}"
            )
        generation_ids = {
            self._placement_generation_id(spec)
            for spec in specs
        }
        if len(generation_ids) != 1:
            raise RuntimeError(
                "durable model realization spans multiple placement generations: "
                f"{identity}"
            )
        placement_generation_id = next(iter(generation_ids))

        compute_by_id = {
            row.allocation_id: row
            for row in self._compute_scheduler.allocations(scope=request.scope)
        }
        adopted_compute: list[ComputeAllocation] = []
        adopted_endpoints: list[EndpointAllocation] = []
        adopted_generations: list[ModelDeploymentGeneration] = []
        replacement_required = False

        for spec in specs:
            generation = self._deployment_runtime.generation(spec.deployment_id)
            applied = generation.applied_runtime_digest
            if applied is None:
                # The active applied pointer is the sole authority that a warm
                # physical generation remains adoptable. Terminal clear
                # tombstones may still identify a stale process left by a crash
                # window, but that generation must be stopped and retired rather
                # than reconstructed from current launch-time host conditions.
                replacement_required = True
            index = self._replica_index(spec)
            compute_id = (
                f"model-realization:{identity}:"
                f"{placement_generation_id}:{index}:compute"
            )
            endpoint_id = (
                f"model-realization:{identity}:"
                f"{placement_generation_id}:{index}:endpoint"
            )
            try:
                compute_seed = compute_by_id[compute_id]
            except KeyError as exc:
                raise RuntimeError(
                    "durable model realization lost deterministic compute allocation: "
                    f"{spec.deployment_id}:{compute_id}"
                ) from exc
            endpoint_seed = self._endpoint_allocations.get(endpoint_id)
            if endpoint_seed is None:
                raise RuntimeError(
                    "durable model realization lost deterministic endpoint allocation: "
                    f"{spec.deployment_id}:{endpoint_id}"
                )
            if applied is not None:
                if compute_seed.binding_binder_identity_digest not in {None, applied}:
                    raise RuntimeError(
                        "durable model compute generation is bound to another runtime: "
                        f"{spec.deployment_id}"
                    )
                if endpoint_seed.binding_binder_identity_digest not in {None, applied}:
                    raise RuntimeError(
                        "durable model endpoint generation is bound to another runtime: "
                        f"{spec.deployment_id}"
                    )
            if (
                compute_seed.gpu_ids != spec.gpu_devices
                or endpoint_seed.endpoint.host != request.endpoint_host
            ):
                raise RuntimeError(
                    "durable model realization physical allocation identity drifted: "
                    f"{spec.deployment_id}"
                )
            compute = self._compute_scheduler.reacquire(
                compute_seed,
                ttl_seconds=self._compute_lease_guards.policy.ttl_seconds,
            )
            endpoint = self._endpoint_allocations.reacquire(endpoint_seed)
            adopted_compute.append(compute)
            adopted_endpoints.append(endpoint)
            adopted_generations.append(generation)

        if replacement_required:
            cleanup = _PendingModelReplicaCleanup(
                cleanup_id=placement_generation_id,
                specs=specs,
                compute_rows=tuple(adopted_compute),
                endpoint_rows=tuple(adopted_endpoints),
                deployment_runtime=self._deployment_runtime,
                compute_scheduler=self._compute_scheduler,
                endpoint_allocations=self._endpoint_allocations,
                compute_guard=None,
                endpoint_guard=None,
            )
            try:
                cleanup.close()
            except BaseException:
                self._pending_cleanups[placement_generation_id] = cleanup
                raise
            return None

        compute_guard = self._compute_lease_guards.create(tuple(adopted_compute))
        endpoint_guard = self._endpoint_lease_guards.create(
            tuple(adopted_endpoints)
        )
        compute_guard.start()
        endpoint_guard.start()
        try:
            placements: list[ModelReplicaPlacement] = []
            for index, (spec, compute, endpoint, generation) in enumerate(
                zip(
                    specs,
                    adopted_compute,
                    adopted_endpoints,
                    adopted_generations,
                    strict=True,
                )
            ):
                status = self._deployment_runtime.status(spec.deployment_id)
                if status.runtime_state is ModelRuntimeState.STOPPED:
                    # Durable identity does not imply durable physical capacity.
                    # A stopped warm generation may have outlived the free VRAM
                    # that originally admitted it. Re-prove the exact placement
                    # after fencing reacquisition and before asking the service
                    # layer to restart on that GPU. A still-bound stopped row is
                    # itself stale ownership evidence and must be re-placed.
                    if (
                        compute.is_bound
                        or not self._compute_scheduler.unbound_placement_satisfies(
                            compute,
                            request.effective_compute,
                        )
                    ):
                        raise _ModelPlacementCapacityDrift(
                            spec.deployment_id, compute, status
                        )
                    try:
                        status = self._deployment_runtime.start(
                            self._deployment_runtime.generation(spec.deployment_id)
                        )
                    except BaseException as start_error:
                        # Capacity can drift again between the pre-start proof and
                        # launch materialization. Re-observe before classifying the
                        # start failure; only proven capacity loss authorizes
                        # placement replacement. Other service failures fail closed.
                        if (
                            not compute.is_bound
                            and not self._compute_scheduler.unbound_placement_satisfies(
                                compute,
                                request.effective_compute,
                            )
                        ):
                            raise _ModelPlacementCapacityDrift(
                                spec.deployment_id, compute, status
                            ) from start_error
                        raise
                if status.runtime_state is not ModelRuntimeState.RUNNING:
                    raise RuntimeError(
                        "durable model realization is not reusable: "
                        f"{spec.deployment_id}:"
                        f"{status.runtime_state.value}:{status.detail}"
                    )
                compute, endpoint, generation, status = (
                    _converge_running_replica_bindings(
                        deployment_runtime=self._deployment_runtime,
                        compute_scheduler=self._compute_scheduler,
                        endpoint_allocations=self._endpoint_allocations,
                        deployment_id=spec.deployment_id,
                        expected_desired_spec_digest=canonical_digest(spec),
                        compute=compute,
                        endpoint=endpoint,
                    )
                )
                placements.append(
                    ModelReplicaPlacement(
                        index,
                        spec.deployment_id,
                        compute,
                        endpoint,
                        spec,
                        generation,
                        status,
                    )
                )
            owner = _ModelReplicaPoolOwner(
                ModelReplicaPoolReport(
                    canonical_digest(request),
                    placement_generation_id,
                    tuple(placements),
                ),
                deployment_runtime=self._deployment_runtime,
                compute_scheduler=self._compute_scheduler,
                endpoint_allocations=self._endpoint_allocations,
                compute_guard=compute_guard,
                endpoint_guard=endpoint_guard,
            )
            owner.assert_healthy()
            return owner
        except _ModelPlacementCapacityDrift as primary:
            cleanup = _PendingModelReplicaCleanup(
                cleanup_id=placement_generation_id,
                specs=specs,
                compute_rows=tuple(adopted_compute),
                endpoint_rows=tuple(adopted_endpoints),
                deployment_runtime=self._deployment_runtime,
                compute_scheduler=self._compute_scheduler,
                endpoint_allocations=self._endpoint_allocations,
                compute_guard=compute_guard,
                endpoint_guard=endpoint_guard,
            )
            try:
                cleanup.close()
            except BaseException as cleanup_error:
                self._pending_cleanups[placement_generation_id] = cleanup
                raise BaseExceptionGroup(
                    "durable model placement drift cleanup failed",
                    [
                        *_exception_leaves(primary),
                        *_exception_leaves(cleanup_error),
                    ],
                ) from primary
            # Exact durable identity remains valid; only its old physical
            # placement was invalidated. Returning no owner makes ensure()
            # materialize the same request through the canonical scheduler.
            return None
        except BaseException:
            try:
                endpoint_guard.close()
            finally:
                compute_guard.close()
            raise

    def ensure(self, request: ModelReplicaPoolRequest) -> ModelReplicaPoolLease:
        if not isinstance(request, ModelReplicaPoolRequest):
            raise TypeError("model replica pool requires ModelReplicaPoolRequest")
        identity = request.runtime_identity_digest
        realization_lock = self._realization_lock(identity)

        # Same realization is single-flight in-process. Different realizations
        # never hold the global lifecycle lock while doing physical work.
        with realization_lock:
            with self._lifecycle_lock:
                if self._closed:
                    raise RuntimeError("model replica pool runtime is closed")
                if self._closing:
                    raise RuntimeError("model replica pool runtime is closing")
                self._retry_pending_cleanups_locked()
                owner = self._owners_by_runtime_identity.get(identity)
                if owner is not None:
                    owner.assert_healthy()
                    return self._consumer_locked(owner)
                self._materializations_in_flight += 1

            owner = None
            try:
                singleflight = self._realization_singleflight
                if singleflight is None:
                    singleflight = ContentAddressedSingleFlight(
                        request.cwd.expanduser().resolve().parent
                        / "runtime-fabric"
                        / "single-flight"
                    )
                with singleflight.producer("model-realization", identity):
                    owner = self._adopt_durable_owner_locked(request)
                    if owner is None:
                        owner = self._materialize_owner_locked(request)
            finally:
                with self._lifecycle_lock:
                    self._materializations_in_flight -= 1
                    self._lifecycle_changed.notify_all()

            with self._lifecycle_lock:
                if self._closed or self._closing:
                    # This controller is shutting down. Preserve the durable
                    # realization but relinquish this process's heartbeat guards.
                    assert owner is not None
                    owner.detach()
                    raise RuntimeError(
                        "model replica pool runtime closed during realization materialization"
                    )
                if identity in self._owners_by_runtime_identity:
                    # The per-identity lock makes this impossible within one
                    # process; keep the assertion as a corruption fence.
                    owner.detach()
                    raise RuntimeError("model runtime identity was materialized twice")
                assert owner is not None
                self._owners_by_runtime_identity[identity] = owner
                return self._consumer_locked(owner)

    def _materialize_owner_locked(
        self,
        request: ModelReplicaPoolRequest,
    ) -> _ModelReplicaPoolOwner:
        if not isinstance(request, ModelReplicaPoolRequest):
            raise TypeError("model replica pool requires ModelReplicaPoolRequest")
        request_digest = canonical_digest(request)
        compute_requirement = request.effective_compute
        target_count = self._target_count(request)
        excluded_gpus: frozenset[tuple[str, str]] = frozenset()

        # A shared host can change underneath us between placement and a long
        # model load. Every capacity-drift retry excludes at least one additional
        # physical GPU for this realization attempt, so retries are bounded by
        # physical device cardinality without a magic attempt count.
        while True:
            placement_generation_id = uuid4().hex
            compute_rows: list[ComputeAllocation] = []
            endpoint_rows: list[EndpointAllocation] = []
            specs: list[ModelDeploymentSpec] = []
            compute_guard = None
            endpoint_guard = None
            try:
                index = 0
                while target_count is None or index < target_count:
                    allocation_id = (
                        f"model-realization:{request.runtime_identity_digest}:"
                        f"{placement_generation_id}:{index}:compute"
                    )
                    try:
                        compute = self._compute_scheduler.allocate(
                            allocation_id,
                            request.scope,
                            compute_requirement,
                            placement_scope=request.scope,
                            ttl_seconds=(
                                self._compute_lease_guards.policy.ttl_seconds
                            ),
                            excluded_gpus=excluded_gpus,
                        )
                    except ComputePlacementUnavailable:
                        if target_count is None and compute_rows:
                            break
                        raise
                    compute_rows.append(compute)
                    endpoint = self._endpoint_allocations.allocate_auto(
                        allocation_id=(
                            f"model-realization:{request.runtime_identity_digest}:"
                            f"{placement_generation_id}:{index}:endpoint"
                        ),
                        holder_scope=request.scope,
                        owner_scope=PLATFORM_SCOPE,
                        ownership=ResourceOwnership.PLATFORM_MANAGED,
                        purpose=(
                            f"model-realization:{request.runtime_identity_digest}"
                        ),
                        host=request.endpoint_host,
                        candidate_count=request.endpoint_candidate_count,
                    )
                    endpoint_rows.append(endpoint)
                    spec = self._deployment(
                        request,
                        replica_index=index,
                        placement_generation_id=placement_generation_id,
                        endpoint=endpoint,
                        compute=compute,
                    )
                    specs.append(self._catalog.put_deployment(spec))
                    index += 1

                if not specs:
                    raise RuntimeError(
                        "automatic model replica pool produced no deployment"
                    )

                compute_guard = self._compute_lease_guards.create(
                    tuple(compute_rows)
                )
                endpoint_guard = self._endpoint_lease_guards.create(
                    tuple(endpoint_rows)
                )
                compute_guard.start()
                endpoint_guard.start()

                try:
                    reconciled = self._fleet.reconcile()
                except BaseException as reconcile_error:
                    # Launch materialization can fail before Fleet has a status
                    # row to return. Do not classify by engine/CUDA error text.
                    # Re-observe each still-unbound allocation using the same
                    # compute requirement that admitted it; proven physical
                    # capacity loss enters the canonical placement-drift retry.
                    for compute, spec in zip(
                        compute_rows, specs, strict=True
                    ):
                        if (
                            not compute.is_bound
                            and not self._compute_scheduler.unbound_placement_satisfies(
                                compute,
                                compute_requirement,
                            )
                        ):
                            status = ModelDeploymentStatus(
                                spec.deployment_id,
                                spec.service_id,
                                spec.desired_state,
                                ModelRuntimeState.ERROR,
                                None,
                                (
                                    "fleet reconcile failed before service binding: "
                                    + type(reconcile_error).__name__
                                ),
                            )
                            raise _ModelPlacementCapacityDrift(
                                spec.deployment_id, compute, status
                            ) from reconcile_error
                    raise
                status_by_id = {
                    row.deployment_id: row
                    for row in reconciled
                    if row.deployment_id
                    in {spec.deployment_id for spec in specs}
                }
                placements: list[ModelReplicaPlacement] = []
                for index, (compute, endpoint, spec) in enumerate(
                    zip(compute_rows, endpoint_rows, specs, strict=True)
                ):
                    try:
                        status = status_by_id[spec.deployment_id]
                    except KeyError as exc:
                        raise RuntimeError(
                            "model fleet omitted deployment status: "
                            f"{spec.deployment_id}"
                        ) from exc
                    if status.runtime_state is not ModelRuntimeState.RUNNING:
                        # Do not classify by CUDA/OOM strings. The compute
                        # authority re-observes this exact still-unbound placement
                        # using the same hard requirement that admitted it. Only
                        # proven physical drift authorizes re-placement.
                        if not self._compute_scheduler.unbound_placement_satisfies(
                            compute,
                            compute_requirement,
                        ):
                            raise _ModelPlacementCapacityDrift(
                                spec.deployment_id, compute, status
                            )
                        raise RuntimeError(
                            "automatic model replica failed: "
                            f"{spec.deployment_id}: "
                            f"{status.runtime_state.value}:{status.detail}"
                        )
                    bound_compute, bound, generation, status = (
                        _converge_running_replica_bindings(
                            deployment_runtime=self._deployment_runtime,
                            compute_scheduler=self._compute_scheduler,
                            endpoint_allocations=self._endpoint_allocations,
                            deployment_id=spec.deployment_id,
                            expected_desired_spec_digest=canonical_digest(spec),
                            compute=compute,
                            endpoint=endpoint,
                        )
                    )
                    placements.append(
                        ModelReplicaPlacement(
                            index,
                            spec.deployment_id,
                            bound_compute,
                            bound,
                            spec,
                            generation,
                            status,
                        )
                    )

                report = ModelReplicaPoolReport(
                    request_digest,
                    placement_generation_id,
                    tuple(placements),
                )
                owner = _ModelReplicaPoolOwner(
                    report,
                    deployment_runtime=self._deployment_runtime,
                    compute_scheduler=self._compute_scheduler,
                    endpoint_allocations=self._endpoint_allocations,
                    compute_guard=compute_guard,
                    endpoint_guard=endpoint_guard,
                )
                owner.assert_healthy()
                return owner
            except BaseException as primary:
                cleanup = _PendingModelReplicaCleanup(
                    cleanup_id=placement_generation_id,
                    specs=tuple(specs),
                    compute_rows=tuple(compute_rows),
                    endpoint_rows=tuple(endpoint_rows),
                    deployment_runtime=self._deployment_runtime,
                    compute_scheduler=self._compute_scheduler,
                    endpoint_allocations=self._endpoint_allocations,
                    compute_guard=compute_guard,
                    endpoint_guard=endpoint_guard,
                )
                try:
                    cleanup.close()
                except BaseException as cleanup_error:
                    self._pending_cleanups[placement_generation_id] = cleanup
                    raise BaseExceptionGroup(
                        "model replica pool creation failed with pending cleanup",
                        [
                            *_exception_leaves(primary),
                            *_exception_leaves(cleanup_error),
                        ],
                    ) from primary

                if isinstance(primary, _ModelPlacementCapacityDrift):
                    new_exclusions = excluded_gpus | frozenset(
                        (primary.compute.host_id, gpu_id)
                        for gpu_id in primary.compute.gpu_ids
                    )
                    if new_exclusions == excluded_gpus:
                        raise RuntimeError(
                            "model placement drift recovery made no physical "
                            "progress"
                        ) from primary
                    excluded_gpus = new_exclusions
                    continue
                raise


__all__ = [
    "LocalModelReplicaPoolRuntime",
    "ModelReplicaPlacement",
    "ModelReplicaPoolLease",
    "ModelReplicaPoolReport",
    "ModelReplicaPoolRequest",
]
