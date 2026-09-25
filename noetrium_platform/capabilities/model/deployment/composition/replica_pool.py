from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Callable
from time import time
from uuid import uuid4

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentCatalogPort,
    ModelDeploymentGeneration,
    ModelDeploymentRuntimePort,
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
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.substrate.api import PLATFORM_SCOPE, ScopeIdentity
from noetrium_platform.substrate.api import (
    EndpointAllocation,
    EndpointAllocationPort,
    EndpointBindingProof,
    EndpointLeaseGuardFactoryPort,
)
from noetrium_platform.substrate.api import (
    ComputeAllocation,
    ComputeAllocationBatch,
    ComputeAllocationRequest,
    ComputeBindingProof,
    ComputeLeaseGuardFactoryPort,
    ComputePlacementUnavailable,
    ComputeRequirement,
    ComputeSchedulerPort,
)
from noetrium_platform.substrate.api import ResourceOwnership


_BINDING_CONVERGENCE_ATTEMPTS = 4


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
    python_environment_id: str
    cwd: Path
    compute: ComputeRequirement
    model_stack: ModelStackSpec | None = None
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
            (self.python_environment_id, "python_environment_id"),
            (self.endpoint_host, "endpoint_host"),
        ):
            if not value.strip():
                raise ValueError(f"model replica pool {field_name} is required")
        if self.engine not in {"vllm", "sglang"}:
            raise ValueError("model replica pool supports vllm or sglang")
        if self.compute.gpu_count <= 0:
            raise ValueError("automatic model replica pools currently require GPU resources")
        if self.model_stack is not None:
            if not isinstance(self.model_stack, ModelStackSpec):
                raise TypeError("model replica pool model_stack must be ModelStackSpec")
            if self.model_stack.identity.model_id != self.model_id:
                raise ValueError("model replica pool model_id must match frozen model stack")
            if self.model_stack.identity.engine.lower() != self.engine:
                raise ValueError("model replica pool engine must match frozen model stack")
            if self.extra_args:
                raise ValueError(
                    "model replica pool extra_args are forbidden when model_stack is frozen; "
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
        if self.model_stack is None or self.engine != "vllm":
            return self.compute
        return reconcile_vllm_compute_requirement(
            self.model_stack,
            self.compute,
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


class ModelReplicaPoolLease:
    """Own model services and both resource-lease families for one pool.

    Cleanup is dependency ordered and retryable. Serving processes must be
    proven gone before lease heartbeats stop, and each resource family is
    released only after its own renewal guard has converged.
    """

    def __init__(
        self,
        report: ModelReplicaPoolReport,
        *,
        deployment_runtime: ModelDeploymentRuntimePort,
        compute_scheduler: ComputeSchedulerPort,
        endpoint_allocations: EndpointAllocationPort,
        compute_guard,
        endpoint_guard,
        on_closed: Callable[["ModelReplicaPoolLease"], None] | None = None,
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
            row.deployment_id: row.generation
            for row in report.placements
        }
        self._current_compute = {
            row.compute.allocation_id: row.compute
            for row in report.placements
        }
        self._current_endpoints = {
            row.endpoint.allocation_id: row.endpoint
            for row in report.placements
        }
        self._closed = False
        self._on_closed = on_closed
        self._lifecycle_lock = RLock()

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

    def _retire_current_generation(
        self,
        row: ModelReplicaPlacement,
    ) -> ModelDeploymentGeneration:
        fallback = self._current_generations[row.deployment_id]
        try:
            generation = self._current_generation(row)
        except (KeyError, FileNotFoundError):
            # Absence of the desired row is not, by itself, physical convergence.
            # Let the deployment runtime validate the last exact applied
            # generation (or prove terminal retirement) before resources move.
            generation = fallback
        self._deployment_runtime.remove_deployment(generation)
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
                raise RuntimeError("model replica pool lease is closed")
            self._compute_guard.assert_healthy()
            self._endpoint_guard.assert_healthy()
            for row in self.report.placements:
                self._converge_running_generation(row)

    def close(self) -> None:
        callback = None
        with self._lifecycle_lock:
            was_closed = self._closed
            self._close_locked()
            if not was_closed and self._closed:
                callback = self._on_closed
        # Never acquire the owning pool lock while holding the lease lock.
        # close_all() takes the inverse order (pool -> lease), so invoking the
        # registry callback under the lease lock would permit an ABBA deadlock
        # with an external concurrent lease.close().
        if callback is not None:
            callback(self)

    def _close_locked(self) -> None:
        if self._closed:
            return

        errors: list[BaseException] = []
        for row in reversed(self.report.placements):
            if row.deployment_id in self._removed_deployment_ids:
                continue
            try:
                generation = self._retire_current_generation(row)
            except BaseException as exc:
                errors.append(exc)
            else:
                self._current_generations[row.deployment_id] = generation
                self._removed_deployment_ids.add(row.deployment_id)

        if len(self._removed_deployment_ids) != len(self.report.placements):
            raise ExceptionGroup("model replica pool cleanup failed", errors)

        if not self._endpoint_guard_closed:
            try:
                self._endpoint_guard.close()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._endpoint_guard_closed = True
        if not self._compute_guard_closed:
            try:
                self._compute_guard.close()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._compute_guard_closed = True

        if self._endpoint_guard_closed:
            for row in reversed(self.report.placements):
                allocation_id = row.endpoint.allocation_id
                if allocation_id in self._released_endpoint_ids:
                    continue
                try:
                    # Every deployment generation was stopped above. Use the
                    # recovery-aware retirement path so a heartbeat-expired
                    # lease cannot strand ownership after physical convergence.
                    self._endpoint_allocations.recover_release(
                        self._current_endpoints[allocation_id]
                    )
                except BaseException as exc:
                    errors.append(exc)
                else:
                    self._released_endpoint_ids.add(allocation_id)

        if self._compute_guard_closed:
            for row in reversed(self.report.placements):
                allocation_id = row.compute.allocation_id
                if allocation_id in self._released_compute_ids:
                    continue
                try:
                    self._compute_scheduler.recover_release(
                        self._current_compute[allocation_id]
                    )
                except BaseException as exc:
                    errors.append(exc)
                else:
                    self._released_compute_ids.add(allocation_id)

        if errors:
            raise ExceptionGroup("model replica pool cleanup failed", errors)

        self._closed = (
            self._endpoint_guard_closed
            and self._compute_guard_closed
            and len(self._released_endpoint_ids) == len(self.report.placements)
            and len(self._released_compute_ids) == len(self.report.placements)
        )
        if not self._closed:
            raise RuntimeError("model replica pool cleanup did not converge")
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
                expected_desired_digest = canonical_digest(spec)
                try:
                    try:
                        generation = self._deployment_runtime.generation(
                            spec.deployment_id
                        )
                    except (KeyError, FileNotFoundError):
                        # Desired-state absence cannot prove that the applied
                        # process generation is gone. Ask the runtime to retire
                        # the known desired identity with a no-applied fallback;
                        # the real runtime only accepts this when no applied
                        # generation remains.
                        generation = ModelDeploymentGeneration(
                            spec.deployment_id,
                            expected_desired_digest,
                            None,
                        )
                    if generation.desired_spec_digest != expected_desired_digest:
                        raise RuntimeError(
                            "model replica cleanup lost desired generation authority: "
                            f"{spec.deployment_id}"
                        )
                    self._deployment_runtime.remove_deployment(generation)
                except BaseException as exc:
                    errors.append(exc)
                else:
                    self._removed_deployment_ids.add(spec.deployment_id)

            deployments_removed = (
                len(self._removed_deployment_ids) == len(self._specs)
            )
            if not deployments_removed:
                raise ExceptionGroup(
                    "pending model replica cleanup did not stop all deployments",
                    errors,
                )

            if not self._endpoint_guard_closed:
                try:
                    self._endpoint_guard.close()
                except BaseException as exc:
                    errors.append(exc)
                else:
                    self._endpoint_guard_closed = True
            if not self._compute_guard_closed:
                try:
                    self._compute_guard.close()
                except BaseException as exc:
                    errors.append(exc)
                else:
                    self._compute_guard_closed = True

            if self._endpoint_guard_closed:
                for endpoint in reversed(self._endpoint_rows):
                    if endpoint.allocation_id in self._released_endpoint_ids:
                        continue
                    try:
                        self._endpoint_allocations.recover_release(endpoint)
                    except BaseException as exc:
                        errors.append(exc)
                    else:
                        self._released_endpoint_ids.add(endpoint.allocation_id)

            if self._compute_guard_closed:
                for compute in reversed(self._compute_rows):
                    if compute.allocation_id in self._released_compute_ids:
                        continue
                    try:
                        self._compute_scheduler.recover_release(compute)
                    except BaseException as exc:
                        errors.append(exc)
                    else:
                        self._released_compute_ids.add(compute.allocation_id)

            if errors:
                raise ExceptionGroup(
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
    """Automatically place, expose, start and lease one local model fleet."""

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
    ) -> None:
        self._catalog = deployment_catalog
        self._deployment_runtime = deployment_runtime
        self._fleet = fleet
        self._compute_scheduler = compute_scheduler
        self._endpoint_allocations = endpoint_allocations
        self._compute_lease_guards = compute_lease_guards
        self._endpoint_lease_guards = endpoint_lease_guards
        self._lifecycle_lock = RLock()
        self._active_leases: dict[str, ModelReplicaPoolLease] = {}
        self._pending_cleanups: dict[str, _PendingModelReplicaCleanup] = {}
        self._closing = False
        self._closed = False

    @property
    def active_lease_count(self) -> int:
        with self._lifecycle_lock:
            return len(self._active_leases)

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
                errors.append(exc)
            else:
                self._pending_cleanups.pop(cleanup_id, None)
        if errors:
            raise ExceptionGroup(
                "model replica pool pending cleanup failed",
                errors,
            )

    def _lease_closed(self, lease: ModelReplicaPoolLease) -> None:
        with self._lifecycle_lock:
            digest = lease.report.report_digest
            current = self._active_leases.get(digest)
            if current is lease:
                self._active_leases.pop(digest, None)

    def close_all(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closing = True
            errors: list[BaseException] = []
            for lease in tuple(self._active_leases.values()):
                try:
                    lease.close()
                except BaseException as exc:
                    errors.append(exc)
                else:
                    # A concurrent external close may have committed lease
                    # teardown but still be waiting to run its registry callback
                    # outside the lease lock. Retire it idempotently under the
                    # pool authority before judging global convergence.
                    self._lease_closed(lease)
            try:
                self._retry_pending_cleanups_locked()
            except BaseException as exc:
                errors.append(exc)
            if errors:
                raise ExceptionGroup(
                    "model replica pool runtime cleanup failed",
                    errors,
                )
            if self._active_leases or self._pending_cleanups:
                raise RuntimeError(
                    "model replica pool runtime cleanup did not retire all ownership"
                )
            self._closed = True

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
            f"{request.pool_id}-generation-{placement_generation_id[:16]}"
            f"-replica-{replica_index:03d}"
        )
        stack = request.model_stack
        engine_args = request.extra_args if stack is None else stack.engine_args
        tensor_parallel = (
            request.compute.gpu_count
            if stack is None
            else stack.tensor_parallel
        )
        common = dict(
            deployment_id=deployment_id,
            scope=request.scope,
            model_id=request.model_id,
            python_environment_id=request.python_environment_id,
            cwd=request.cwd,
            host=endpoint.endpoint.host,
            port=endpoint.endpoint.port,
            tensor_parallel=tensor_parallel,
            gpu_devices=compute.gpu_ids,
            extra_args=engine_args,
        )
        if request.engine == "vllm":
            spec = vllm_deployment(
                **common,
                data_parallel=1,
                pipeline_parallel=1 if stack is None else stack.pipeline_parallel,
            )
        elif request.engine == "sglang":
            spec = sglang_deployment(**common)
        else:
            raise AssertionError(request.engine)
        tags = tuple(sorted({
            *request.tags,
            "auto-managed",
            f"replica-pool:{request.pool_id}",
            f"placement-generation:{placement_generation_id}",
            *(
                ()
                if stack is None
                else (f"model-stack:{stack.digest()}",)
            ),
        }))
        from dataclasses import replace
        return replace(spec, desired_state=ModelDesiredState.RUNNING, tags=tags)

    def ensure(self, request: ModelReplicaPoolRequest) -> ModelReplicaPoolLease:
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("model replica pool runtime is closed")
            if self._closing:
                raise RuntimeError("model replica pool runtime is closing")
            self._retry_pending_cleanups_locked()
            return self._ensure_locked(request)

    def _ensure_locked(
        self,
        request: ModelReplicaPoolRequest,
    ) -> ModelReplicaPoolLease:
        if not isinstance(request, ModelReplicaPoolRequest):
            raise TypeError("model replica pool requires ModelReplicaPoolRequest")
        request_digest = canonical_digest(request)
        placement_generation_id = uuid4().hex
        compute_requirement = request.effective_compute
        target_count = self._target_count(request)
        compute_rows: list[ComputeAllocation] = []
        endpoint_rows: list[EndpointAllocation] = []
        specs: list[ModelDeploymentSpec] = []
        compute_guard = None
        endpoint_guard = None
        try:
            preallocated_compute: dict[str, ComputeAllocation] = {}
            if target_count is not None:
                batch = ComputeAllocationBatch(
                    batch_id=(
                        f"model-pool:{request.pool_id}:"
                        f"{placement_generation_id}:compute"
                    ),
                    requests=tuple(
                        ComputeAllocationRequest(
                            allocation_id=(
                                f"model-pool:{request.pool_id}:"
                                f"{placement_generation_id}:"
                                f"{index}:compute"
                            ),
                            scope=request.scope,
                            requirement=compute_requirement,
                            placement_scope=request.scope,
                        )
                        for index in range(target_count)
                    ),
                )
                reserved = self._compute_scheduler.allocate_batch(
                    batch,
                    ttl_seconds=(
                        self._compute_lease_guards.policy.ttl_seconds
                    ),
                )
                compute_rows.extend(reserved)
                preallocated_compute = {
                    row.allocation_id: row for row in reserved
                }

            index = 0
            while target_count is None or index < target_count:
                allocation_id = (
                    f"model-pool:{request.pool_id}:{placement_generation_id}:"
                    f"{index}:compute"
                )
                if target_count is None:
                    try:
                        compute = self._compute_scheduler.allocate(
                            allocation_id,
                            request.scope,
                            compute_requirement,
                            placement_scope=request.scope,
                            ttl_seconds=(
                                self._compute_lease_guards.policy.ttl_seconds
                            ),
                        )
                    except ComputePlacementUnavailable:
                        if compute_rows:
                            break
                        raise
                    compute_rows.append(compute)
                else:
                    try:
                        compute = preallocated_compute[allocation_id]
                    except KeyError as exc:
                        raise RuntimeError(
                            "atomic model replica compute batch omitted "
                            f"allocation: {allocation_id}"
                        ) from exc
                endpoint = self._endpoint_allocations.allocate_auto(
                    allocation_id=(
                        f"model-pool:{request.pool_id}:{placement_generation_id}:"
                        f"{index}:endpoint"
                    ),
                    holder_scope=request.scope,
                    owner_scope=PLATFORM_SCOPE,
                    ownership=ResourceOwnership.PLATFORM_MANAGED,
                    purpose=f"model-replica:{request.pool_id}",
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
                raise RuntimeError("automatic model replica pool produced no deployment")

            compute_guard = self._compute_lease_guards.create(
                tuple(compute_rows)
            )
            endpoint_guard = self._endpoint_lease_guards.create(
                tuple(endpoint_rows)
            )
            compute_guard.start()
            endpoint_guard.start()

            status_by_id = {
                row.deployment_id: row
                for row in self._fleet.reconcile()
                if row.deployment_id in {spec.deployment_id for spec in specs}
            }
            placements: list[ModelReplicaPlacement] = []
            for index, (compute, endpoint, spec) in enumerate(
                zip(compute_rows, endpoint_rows, specs, strict=True)
            ):
                try:
                    status = status_by_id[spec.deployment_id]
                except KeyError as exc:
                    raise RuntimeError(
                        f"model fleet omitted deployment status: {spec.deployment_id}"
                    ) from exc
                if status.runtime_state is not ModelRuntimeState.RUNNING:
                    raise RuntimeError(
                        f"automatic model replica failed: {spec.deployment_id}: "
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
            lease = ModelReplicaPoolLease(
                report,
                deployment_runtime=self._deployment_runtime,
                compute_scheduler=self._compute_scheduler,
                endpoint_allocations=self._endpoint_allocations,
                compute_guard=compute_guard,
                endpoint_guard=endpoint_guard,
                on_closed=self._lease_closed,
            )
            lease.assert_healthy()
            if report.report_digest in self._active_leases:
                raise RuntimeError(
                    "model replica pool report identity was already registered"
                )
            self._active_leases[report.report_digest] = lease
            return lease
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
                raise ExceptionGroup(
                    "model replica pool creation failed with pending cleanup",
                    [primary, cleanup_error],
                ) from primary
            raise


__all__ = [
    "LocalModelReplicaPoolRuntime",
    "ModelReplicaPlacement",
    "ModelReplicaPoolLease",
    "ModelReplicaPoolReport",
    "ModelReplicaPoolRequest",
]
