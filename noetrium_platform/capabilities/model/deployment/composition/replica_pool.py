from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import time

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentCatalogPort,
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
    ComputeLeaseGuardFactoryPort,
    ComputePlacementUnavailable,
    ComputeRequirement,
    ComputeSchedulerPort,
)
from noetrium_platform.substrate.api import ResourceOwnership


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
        if self.replica_count is not None and (
            type(self.replica_count) is not int or self.replica_count <= 0
        ):
            raise ValueError("replica_count must be positive when provided")
        if type(self.endpoint_candidate_count) is not int or self.endpoint_candidate_count <= 0:
            raise ValueError("endpoint_candidate_count must be positive")


@dataclass(frozen=True, slots=True)
class ModelReplicaPlacement:
    replica_index: int
    deployment_id: str
    compute: ComputeAllocation
    endpoint: EndpointAllocation
    deployment: ModelDeploymentSpec
    status: ModelDeploymentStatus

    @property
    def placement_digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ModelReplicaPoolReport:
    request_digest: str
    placements: tuple[ModelReplicaPlacement, ...]
    report_digest: str = field(init=False)

    def __post_init__(self) -> None:
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
                    "placements": tuple(row.placement_digest for row in self.placements),
                }
            ),
        )


class ModelReplicaPoolLease:
    """Own model services and both resource-lease families for one pool."""

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
        self._closed = False

    def assert_healthy(self) -> None:
        self._compute_guard.assert_healthy()
        self._endpoint_guard.assert_healthy()
        for row in self.report.placements:
            status = self._deployment_runtime.status(row.deployment_id)
            if status.runtime_state is not ModelRuntimeState.RUNNING:
                raise RuntimeError(
                    f"model replica is not running: {row.deployment_id}: "
                    f"{status.runtime_state.value}:{status.detail}"
                )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        errors: list[BaseException] = []
        for row in reversed(self.report.placements):
            try:
                self._deployment_runtime.remove_deployment(row.deployment_id)
            except BaseException as exc:
                errors.append(exc)
        for guard in (self._endpoint_guard, self._compute_guard):
            try:
                guard.close()
            except BaseException as exc:
                errors.append(exc)
        for row in reversed(self.report.placements):
            try:
                self._endpoint_allocations.release(row.endpoint.allocation_id)
            except BaseException as exc:
                errors.append(exc)
            try:
                self._compute_scheduler.release(row.compute.allocation_id)
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup("model replica pool cleanup failed", errors)

    def __enter__(self) -> "ModelReplicaPoolLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


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

    def _target_count(self, request: ModelReplicaPoolRequest) -> int:
        if request.replica_count is not None:
            return request.replica_count
        hosts = self._compute_scheduler.candidates(request.compute, scope=request.scope)
        count = sum(len(host.gpus) // request.compute.gpu_count for host in hosts)
        if count <= 0:
            raise RuntimeError("no automatic model replica capacity is currently available")
        return count

    @staticmethod
    def _deployment(
        request: ModelReplicaPoolRequest,
        *,
        replica_index: int,
        endpoint: EndpointAllocation,
        compute: ComputeAllocation,
    ) -> ModelDeploymentSpec:
        deployment_id = f"{request.pool_id}-replica-{replica_index:03d}"
        common = dict(
            deployment_id=deployment_id,
            scope=request.scope,
            model_id=request.model_id,
            python_environment_id=request.python_environment_id,
            cwd=request.cwd,
            host=endpoint.endpoint.host,
            port=endpoint.endpoint.port,
            tensor_parallel=request.compute.gpu_count,
            gpu_devices=compute.gpu_ids,
            extra_args=request.extra_args,
        )
        if request.engine == "vllm":
            spec = vllm_deployment(**common)
        elif request.engine == "sglang":
            spec = sglang_deployment(**common)
        else:
            raise AssertionError(request.engine)
        tags = tuple(sorted({
            *request.tags,
            "auto-managed",
            f"replica-pool:{request.pool_id}",
        }))
        from dataclasses import replace
        return replace(spec, desired_state=ModelDesiredState.RUNNING, tags=tags)

    def ensure(self, request: ModelReplicaPoolRequest) -> ModelReplicaPoolLease:
        if not isinstance(request, ModelReplicaPoolRequest):
            raise TypeError("model replica pool requires ModelReplicaPoolRequest")
        request_digest = canonical_digest(request)
        target_count = self._target_count(request)
        compute_rows: list[ComputeAllocation] = []
        endpoint_rows: list[EndpointAllocation] = []
        specs: list[ModelDeploymentSpec] = []
        compute_guard = None
        endpoint_guard = None
        try:
            for index in range(target_count):
                allocation_id = f"model-pool:{request.pool_id}:{request_digest[:16]}:{index}:compute"
                try:
                    compute = self._compute_scheduler.allocate(
                        allocation_id,
                        request.scope,
                        request.compute,
                        placement_scope=request.scope,
                        ttl_seconds=self._compute_lease_guards.policy.ttl_seconds,
                    )
                except ComputePlacementUnavailable:
                    if request.replica_count is None and compute_rows:
                        break
                    raise
                compute_rows.append(compute)
                endpoint = self._endpoint_allocations.allocate_auto(
                    allocation_id=(
                        f"model-pool:{request.pool_id}:{request_digest[:16]}:"
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
                    endpoint=endpoint,
                    compute=compute,
                )
                specs.append(self._catalog.put_deployment(spec))

            if not specs:
                raise RuntimeError("automatic model replica pool produced no deployment")

            compute_guard = self._compute_lease_guards.create(
                tuple(row.allocation_id for row in compute_rows)
            )
            endpoint_guard = self._endpoint_lease_guards.create(
                tuple(row.allocation_id for row in endpoint_rows)
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
                bound = self._endpoint_allocations.confirm_bound(
                    EndpointBindingProof(
                        allocation_id=endpoint.allocation_id,
                        endpoint=endpoint.endpoint,
                        lease_fencing_token=endpoint.lease_fencing_token,
                        binder_identity_digest=canonical_digest(spec),
                        observed_at_epoch_s=time(),
                        evidence_ref=status.detail or f"model-ready:{spec.deployment_id}",
                    )
                )
                placements.append(
                    ModelReplicaPlacement(index, spec.deployment_id, compute, bound, spec, status)
                )

            report = ModelReplicaPoolReport(request_digest, tuple(placements))
            lease = ModelReplicaPoolLease(
                report,
                deployment_runtime=self._deployment_runtime,
                compute_scheduler=self._compute_scheduler,
                endpoint_allocations=self._endpoint_allocations,
                compute_guard=compute_guard,
                endpoint_guard=endpoint_guard,
            )
            lease.assert_healthy()
            return lease
        except BaseException:
            for spec in reversed(specs):
                try:
                    self._deployment_runtime.remove_deployment(spec.deployment_id)
                except BaseException:
                    pass
            if endpoint_guard is not None:
                try:
                    endpoint_guard.close()
                except BaseException:
                    pass
            if compute_guard is not None:
                try:
                    compute_guard.close()
                except BaseException:
                    pass
            for endpoint in reversed(endpoint_rows):
                try:
                    self._endpoint_allocations.release(endpoint.allocation_id)
                except BaseException:
                    pass
            for compute in reversed(compute_rows):
                try:
                    self._compute_scheduler.release(compute.allocation_id)
                except BaseException:
                    pass
            raise


__all__ = [
    "LocalModelReplicaPoolRuntime",
    "ModelReplicaPlacement",
    "ModelReplicaPoolLease",
    "ModelReplicaPoolReport",
    "ModelReplicaPoolRequest",
]
