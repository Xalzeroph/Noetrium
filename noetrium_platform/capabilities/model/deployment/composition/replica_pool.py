from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Condition, RLock
from typing import Callable
from uuid import uuid4

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentCatalogPort,
    ModelDeploymentGeneration,
    ModelDeploymentRuntimePort,
    ModelDesiredDeployment,
    ModelDeploymentStatus,
    ModelDesiredState,
    ModelRuntimeState,
)
from noetrium_platform.capabilities.model.deployment.runtime.templates import (
    model_deployment_template_digest,
    sglang_deployment,
    vllm_deployment,
)
from noetrium_platform.capabilities.model.deployment.runtime.vllm_resources import (
    reconcile_vllm_compute_requirement,
)
from noetrium_platform.capabilities.model.deployment.runtime.resource_provider import (
    ModelServicePhysicalProvider,
    model_realization_parameters,
    model_resource_deployment_id,
)
from noetrium_platform.capabilities.model.stack.api import (
    FrozenModelStack,
    model_stack_launch_settings,
    parse_vllm_engine_resource_args,
)
from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    ComplexityBound,
    ComplexityContract,
)
from noetrium_platform.substrate.api import (
    AuthoritySnapshot,
    PLATFORM_SCOPE,
    ComputeInventoryPort,
    ComputePlacementUnavailable,
    ComputeRequirement,
    EndpointCandidatePortSourcePort,
    EndpointProbePort,
    GpuRuntimeObserverPort,
    HostRuntimeObserverPort,
    ResourceAuthorityPort,
    ResourceLeaseHeartbeatFactoryPort,
    ResourceLeaseHeartbeatGuardPort,
    AuthorityLeasePolicy,
    DEFAULT_AUTHORITY_LEASE_POLICY,
    ResourceRealizationSpec,
    NoetriumUnit,
    binding_field,
    claim_field,
    lease_field,
    observation_field,
    physical_field,
    resource_claim,
    NoetriumUnit,
    automatic_endpoint_claim_candidates,
    compute_capacity,
    compute_claim_candidates,
    resource_node,
    resource_topology,
)


MODEL_WARM_DOMINANCE_COMPLEXITY = ComplexityContract(
    algorithm_id="model.warm-dominance.v2",
    implementation_digest=canonical_digest(
        ("model.warm-dominance.v2", "family-maximum-context")
    ),
    time_upper_bound=ComplexityBound.linear("warm_realizations"),
    space_upper_bound=ComplexityBound.linear("warm_capability_families"),
    assumptions=(
        "strict dominance differs only by context length inside one exact serving-contract family",
        "every warm realization can change its family maximum",
    ),
    time_lower_bound=ComplexityBound.linear("warm_realizations"),
)


@dataclass(frozen=True, slots=True)
class _WarmRuntimeCapability:
    model_id: str
    engine: str
    container_digest: str
    tensor_parallel: int
    context_length: int
    max_num_seqs: int | None
    max_num_active_seqs: int | None
    max_num_queued_requests: int | None

    def strictly_dominates(self, other: "_WarmRuntimeCapability") -> bool:
        if type(other) is not _WarmRuntimeCapability:
            raise TypeError("warm runtime dominance requires typed capability")
        return (
            self.model_id == other.model_id
            and self.engine == other.engine
            and self.container_digest == other.container_digest
            and self.tensor_parallel == other.tensor_parallel
            and self.max_num_seqs == other.max_num_seqs
            and self.max_num_active_seqs == other.max_num_active_seqs
            and self.max_num_queued_requests == other.max_num_queued_requests
            and self.context_length > other.context_length
        )


def _positive_deployment_option(
    argv: tuple[str, ...],
    *,
    name: str,
) -> int | None:
    found: int | None = None
    index = 0
    prefix = name + "="
    while index < len(argv):
        token = argv[index]
        raw: str | None = None
        if token == name:
            if index + 1 >= len(argv):
                raise ValueError(f"deployment option requires a value: {name}")
            raw = argv[index + 1]
            index += 1
        elif token.startswith(prefix):
            raw = token[len(prefix):]
        if raw is not None:
            if found is not None:
                raise ValueError(f"deployment option is duplicated: {name}")
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError(
                    f"deployment option must be a positive integer: {name}"
                ) from exc
            if value <= 0:
                raise ValueError(
                    f"deployment option must be a positive integer: {name}"
                )
            found = value
        index += 1
    return found


def _warm_runtime_capability(
    spec: ModelDesiredDeployment,
) -> _WarmRuntimeCapability | None:
    if type(spec) is not ModelDesiredDeployment:
        raise TypeError("warm runtime capability requires ModelDesiredDeployment")
    if spec.engine != "vllm" or not spec.gpu_devices:
        return None
    try:
        context_length = _positive_deployment_option(
            spec.argv,
            name="--max-model-len",
        )
        parsed = parse_vllm_engine_resource_args(spec.argv)
    except ValueError:
        return None
    if context_length is None:
        return None
    return _WarmRuntimeCapability(
        model_id=spec.model_id,
        engine=spec.engine,
        container_digest=spec.container_digest,
        tensor_parallel=len(spec.gpu_devices),
        context_length=context_length,
        max_num_seqs=parsed.max_num_seqs,
        max_num_active_seqs=parsed.max_num_active_seqs,
        max_num_queued_requests=parsed.max_num_queued_requests,
    )


def _dominated_warm_runtime_identities(
    capabilities: dict[str, _WarmRuntimeCapability],
    *,
    reclaimable: frozenset[str],
) -> frozenset[str]:
    """Return reclaimable warm identities strictly dominated by a stronger peer.

    Dominance differs only by context length inside one exact capability class.
    Group once and retain the maximum context per class instead of comparing
    every reclaimable identity against every warm runtime. This is Θ(W), which
    is asymptotically optimal because every capability can affect the maximum.
    """
    if type(reclaimable) is not frozenset:
        raise TypeError("warm reclaimable identities must be frozenset")

    def family_key(
        row: _WarmRuntimeCapability,
    ) -> tuple[object, ...]:
        return (
            row.model_id,
            row.engine,
            row.container_digest,
            row.tensor_parallel,
            row.max_num_seqs,
            row.max_num_active_seqs,
            row.max_num_queued_requests,
        )

    maximum_context_by_family: dict[tuple[object, ...], int] = {}
    for capability in capabilities.values():
        key = family_key(capability)
        current = maximum_context_by_family.get(key)
        if current is None or capability.context_length > current:
            maximum_context_by_family[key] = capability.context_length

    return frozenset(
        identity
        for identity in reclaimable
        if (
            identity in capabilities
            and capabilities[identity].context_length
            < maximum_context_by_family[family_key(capabilities[identity])]
        )
    )


@dataclass(frozen=True, slots=True)
class ModelReplicaPoolRequest:
    """High-level desired model fleet without concrete GPU or port identity."""

    pool_id: str
    scope: NoetriumUnit
    model_id: str
    engine: str
    cwd: Path
    compute: ComputeRequirement
    model_stack: FrozenModelStack
    replica_count: int | None = None
    endpoint_host: str = "127.0.0.1"
    extra_args: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    def __post_init__(self) -> None:
        for value, field_name in (
            (self.pool_id, "pool_id"),
            (self.model_id, "model_id"),
            (self.engine, "engine"),
            (self.endpoint_host, "endpoint_host"),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"model replica pool {field_name} is required")
        if self.engine not in {"vllm", "sglang"}:
            raise ValueError("model replica pool supports vllm or sglang")
        if not isinstance(self.compute, ComputeRequirement):
            raise TypeError("model replica pool compute must be ComputeRequirement")
        if self.compute.gpu_count <= 0:
            raise ValueError("automatic model replica pools require GPU resources")
        if not isinstance(self.model_stack, FrozenModelStack):
            raise TypeError("model replica pool model_stack must be FrozenModelStack")
        if self.model_stack.identity.model_id != self.model_id:
            raise ValueError("model replica pool model_id must match frozen model stack")
        if self.model_stack.identity.engine.lower() != self.engine:
            raise ValueError("model replica pool engine must match frozen model stack")
        if self.extra_args:
            raise ValueError(
                "model replica pool extra_args are forbidden; "
                "put engine arguments in FrozenModelStack.engine_args"
            )
        if self.engine == "vllm":
            if self.model_stack.data_parallel != 1:
                raise ValueError(
                    "automatic vLLM pools use independent replicas; "
                    "internal data_parallel requires explicit auxiliary endpoints"
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
                    "automatic SGLang pools support tensor parallel only"
                )
            required_gpus = self.model_stack.tensor_parallel
        if self.compute.gpu_count != required_gpus:
            raise ValueError(
                "model replica pool compute.gpu_count must match engine topology"
            )
        if self.replica_count is not None and (
            type(self.replica_count) is not int or self.replica_count <= 0
        ):
            raise ValueError("replica_count must be positive when provided")
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
        return canonical_digest(
            {
                "schema": "noetrium.model-replica-runtime-identity.v3",
                "scope": self.scope,
                "model_id": self.model_id,
                "engine": self.engine,
                "launch_template_digest": model_deployment_template_digest(self.engine),
                "cwd": str(self.cwd.expanduser().resolve()),
                "compute": self.effective_compute,
                "model_stack_digest": self.model_stack.digest(),
                "replica_count": self.replica_count,
                "endpoint_host": self.endpoint_host,
            }
        )


@dataclass(frozen=True, slots=True)
class ModelReplicaPlacement:
    """Immutable projection of Authority claims plus model runtime state."""

    replica_index: int
    deployment_id: str
    host_id: str
    gpu_ids: tuple[str, ...]
    gpu_memory_reservation_bytes: tuple[int, ...]
    endpoint_host: str
    endpoint_port: int
    compute_resource_key: str
    endpoint_resource_key: str
    service_resource_key: str
    compute_claim_id: str
    endpoint_claim_id: str
    service_claim_id: str
    deployment: ModelDesiredDeployment
    generation: ModelDeploymentGeneration
    status: ModelDeploymentStatus
    def __post_init__(self) -> None:
        if type(self.replica_index) is not int or self.replica_index < 0:
            raise ValueError("model replica index must be non-negative")
        if not self.deployment_id or not self.host_id or not self.endpoint_host:
            raise ValueError("model replica placement identity is required")
        if not 1 <= self.endpoint_port <= 65535:
            raise ValueError("model replica endpoint port is invalid")
        if len(self.gpu_memory_reservation_bytes) != len(self.gpu_ids):
            raise ValueError("GPU reservations must align with gpu_ids")

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
        ids = tuple(row.deployment_id for row in self.placements)
        if len(ids) != len(set(ids)):
            raise ValueError("model replica pool deployment ids must be unique")
        object.__setattr__(
            self,
            "report_digest",
            canonical_digest(
                {
                    "request_digest": self.request_digest,
                    "placements": tuple(
                        row.placement_digest for row in self.placements
                    ),
                }
            ),
        )


def _claim_attributes(claim: NoetriumUnit, kind: str) -> dict[str, object]:
    attrs = dict(claim_field(claim, "attributes") or {})
    if attrs.get("kind") != kind:
        raise RuntimeError(
            f"resource claim {claim_field(claim, "claim_id")!r} is not kind {kind!r}"
        )
    return attrs
def _single_current_claim(
    snapshot: AuthoritySnapshot,
    resource_key: str,
) -> NoetriumUnit:
    rows = snapshot.current_claims_for(resource_key)
    if len(rows) != 1:
        raise RuntimeError(
            "model replica resource must have exactly one current claim: "
            + resource_key
        )
    return rows[0]


class _ModelReplicaPoolOwner:
    """Own one warm model realization; all durable resource truth is Authority."""

    def __init__(
        self,
        report: ModelReplicaPoolReport,
        *,
        deployment_runtime: ModelDeploymentRuntimePort,
        authority: ResourceAuthorityPort,
        provider: ModelServicePhysicalProvider,
        topologies: tuple[object, ...],
    ) -> None:
        self.report = report
        self._deployment_runtime = deployment_runtime
        self._authority = authority
        self._provider = provider
        self._topologies = topologies
        self._closed = False
        self._lock = RLock()

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def assert_healthy(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("model replica owner is closed")
            resource_keys = frozenset(
                key
                for row in self.report.placements
                for key in (
                    row.compute_resource_key,
                    row.endpoint_resource_key,
                    row.service_resource_key,
                )
            )
            snapshot = self._authority.snapshot_for_resource_keys(resource_keys)
            for row in self.report.placements:
                compute = _single_current_claim(snapshot, row.compute_resource_key)
                endpoint = _single_current_claim(snapshot, row.endpoint_resource_key)
                service = _single_current_claim(snapshot, row.service_resource_key)
                if (
                    claim_field(compute, "claim_id") != row.compute_claim_id
                    or claim_field(endpoint, "claim_id") != row.endpoint_claim_id
                    or claim_field(service, "claim_id") != row.service_claim_id
                ):
                    raise RuntimeError(
                        "model replica Authority claim generation drifted: "
                        + row.deployment_id
                    )
                binding = snapshot.binding_for(row.service_resource_key)
                if (
                    binding is None
                    or physical_field(binding_field(binding, "physical_identity"), "provider_kind")
                    != ModelServicePhysicalProvider.provider_kind
                    or physical_field(binding_field(binding, "physical_identity"), "physical_id") != row.deployment_id
                ):
                    raise RuntimeError(
                        "model replica Authority physical binding drifted: "
                        + row.deployment_id
                    )
                status = self._deployment_runtime.status(row.deployment_id)
                if status.runtime_state is not ModelRuntimeState.RUNNING:
                    raise RuntimeError(
                        "model replica is not running: "
                        f"{row.deployment_id}:{status.runtime_state.value}"
                    )

    def detach(self) -> None:
        """Detach process-local ownership without changing warm realization."""
        with self._lock:
            self._closed = True

class ModelReplicaPoolLease:
    """Authority-backed consumer handle for one warm model realization."""

    def __init__(
        self,
        owner: _ModelReplicaPoolOwner,
        *,
        consumer_lease_id: str,
        authority: ResourceAuthorityPort,
        authority_lease: NoetriumUnit,
        heartbeat_guard: ResourceLeaseHeartbeatGuardPort,
        on_closed: Callable[["ModelReplicaPoolLease"], None],
    ) -> None:
        if not consumer_lease_id:
            raise ValueError("model replica consumer identity is required")
        self.report = owner.report
        self.consumer_lease_id = consumer_lease_id
        self._owner = owner
        self._authority = authority
        self._authority_lease = authority_lease
        self._heartbeat_guard = heartbeat_guard
        self._on_closed = on_closed
        self._closed = False
        self._lock = RLock()
    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def assert_healthy(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("model replica consumer is closed")
            self._heartbeat_guard.assert_healthy()
            self._owner.assert_healthy()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        errors: list[BaseException] = []
        try:
            self._heartbeat_guard.close()
        except BaseException as exc:
            errors.append(exc)
        try:
            self._authority.release_lease(self._authority_lease)
        except BaseException as exc:
            errors.append(exc)
        self._on_closed(self)
        if errors:
            raise BaseExceptionGroup("model replica consumer release failed", errors)

    def __enter__(self) -> "ModelReplicaPoolLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


class LocalModelReplicaPoolRuntime:
    """Warm model fabric backed only by UniversalResourceAuthority claims."""

    def __init__(
        self,
        *,
        deployment_catalog: ModelDeploymentCatalogPort,
        deployment_runtime: ModelDeploymentRuntimePort,
        resource_authority: ResourceAuthorityPort,
        compute_inventory: ComputeInventoryPort,
        endpoint_candidates: EndpointCandidatePortSourcePort,
        endpoint_probe: EndpointProbePort,
        gpu_runtime_observer: GpuRuntimeObserverPort,
        host_runtime_observer: HostRuntimeObserverPort,
        runtime_fabric_resource_key: str | None = None,
        runtime_fabric_consumer_lease_id: str | None = None,
        consumer_lease_guard_factory: ResourceLeaseHeartbeatFactoryPort | None = None,
        consumer_lease_policy: AuthorityLeasePolicy = DEFAULT_AUTHORITY_LEASE_POLICY,
        consumer_holder_id: str | None = None,
    ) -> None:
        self._catalog = deployment_catalog
        self._deployment_runtime = deployment_runtime
        self._authority = resource_authority
        self._provider = ModelServicePhysicalProvider(
            catalog=deployment_catalog,
            runtime=deployment_runtime,
        )
        self._compute_inventory = compute_inventory
        self._endpoint_candidates = endpoint_candidates
        self._endpoint_probe = endpoint_probe
        self._gpu_runtime = gpu_runtime_observer
        self._host_runtime = host_runtime_observer
        self._runtime_fabric_resource_key = runtime_fabric_resource_key
        self._runtime_fabric_consumer_lease_id = (
            runtime_fabric_consumer_lease_id
        )
        if consumer_lease_guard_factory is None:
            raise TypeError("model replica pool requires consumer ResourceLeaseHeartbeatFactoryPort")
        if not isinstance(consumer_lease_guard_factory, ResourceLeaseHeartbeatFactoryPort):
            raise TypeError("model replica pool consumer lease factory is invalid")
        if not isinstance(consumer_lease_policy, AuthorityLeasePolicy):
            raise TypeError("model replica pool consumer lease policy is invalid")
        if type(consumer_holder_id) is not str or not consumer_holder_id.strip():
            raise ValueError("model replica pool consumer holder id is required")
        self._consumer_lease_guard_factory = consumer_lease_guard_factory
        self._consumer_lease_policy = consumer_lease_policy
        self._consumer_holder_id = consumer_holder_id.strip()
        self._lock = RLock()
        self._changed = Condition(self._lock)
        self._identity_locks: dict[str, RLock] = {}
        self._materializations = 0
        self._owners: dict[str, _ModelReplicaPoolOwner] = {}
        self._leases: dict[str, ModelReplicaPoolLease] = {}
        self._closing = False
        self._closed = False
    @property
    def active_lease_count(self) -> int:
        with self._lock:
            return len(self._leases)

    @property
    def warm_owner_count(self) -> int:
        with self._lock:
            return len(self._owners)

    @property
    def pending_cleanup_count(self) -> int:
        return 0

    def _identity_lock(self, identity: str) -> RLock:
        with self._lock:
            return self._identity_locks.setdefault(identity, RLock())

    def _lease_closed(self, lease: ModelReplicaPoolLease) -> None:
        with self._lock:
            if self._leases.get(lease.consumer_lease_id) is lease:
                self._leases.pop(lease.consumer_lease_id, None)

    @staticmethod
    def _consumer_resource_key(runtime_identity: str) -> str:
        if type(runtime_identity) is not str or not runtime_identity.strip():
            raise ValueError("model runtime identity is required")
        return "model-runtime-consumers:" + runtime_identity.strip()

    def _reserve_consumer(self, runtime_identity: str):
        """Admit the physical consumer BEFORE observing/creating its replica.

        The cross-process Authority lease excludes the zero-consumer
        retirement fence for the full materialization interval. A lease
        acquired only after deployment cannot protect deployment from a
        concurrent warm-GC or another pool's shutdown.
        """
        local_id = uuid4().hex
        authority_lease = self._authority.acquire_ttl_lease(
            lease_id="model-runtime-consumer:" + local_id,
            resource_key=self._consumer_resource_key(runtime_identity),
            holder_key=self._consumer_holder_id,
            owner_scope=PLATFORM_SCOPE,
            ttl_seconds=self._consumer_lease_policy.ttl_seconds,
            metadata={
                "kind": "model-runtime-consumer",
                "runtime_identity": runtime_identity,
            },
        )
        try:
            guard = self._consumer_lease_guard_factory.create((authority_lease,))
            guard.start()
        except BaseException:
            self._authority.release_lease(authority_lease)
            raise
        return local_id, authority_lease, guard

    def _consumer(
        self,
        owner: _ModelReplicaPoolOwner,
        runtime_identity: str,
        *,
        reservation=None,
    ) -> ModelReplicaPoolLease:
        local_id, authority_lease, guard = (
            self._reserve_consumer(runtime_identity)
            if reservation is None else reservation
        )
        lease = ModelReplicaPoolLease(
            owner,
            consumer_lease_id=local_id,
            authority=self._authority,
            authority_lease=authority_lease,
            heartbeat_guard=guard,
            on_closed=self._lease_closed,
        )
        self._leases[lease.consumer_lease_id] = lease
        return lease

    @staticmethod
    def _resource_keys(
        identity: str,
        index: int,
    ) -> tuple[str, str, str]:
        prefix = f"model:{identity}:replica:{index:03d}"
        return (
            prefix + ":compute",
            prefix + ":endpoint",
            prefix + ":service",
        )

    def _topology(self, identity: str, index: int):
        compute_key, endpoint_key, service_key = self._resource_keys(
            identity,
            index,
        )
        return resource_topology(
            f"model-replica:{identity[:24]}:{index:03d}",
            resources=(
                resource_node(
                    "compute",
                    kind="compute",
                    authority_key=compute_key,
                ),
                resource_node(
                    "endpoint",
                    kind="network-endpoint",
                    authority_key=endpoint_key,
                ),
                resource_node(
                    "service",
                    kind="model-service",
                    authority_key=service_key,
                    realization=True,
                ),
            ),
            requires=(
                ("endpoint", "compute"),
                ("service", "endpoint"),
            ),
        )

    def _endpoint_claims(
        self,
        *,
        snapshot: AuthoritySnapshot,
        generation: int,
        resource_key: str,
        holder_key: str,
        consumer_resource_key: str,
        allocation_id: str,
        request: ModelReplicaPoolRequest,
        scope_generation: int,
        scope_lease_id: str | None,
    ) -> tuple[NoetriumUnit, ...]:
        return automatic_endpoint_claim_candidates(
            resource_key=resource_key,
            holder_key=holder_key,
            generation=generation,
            consumer_resource_key=consumer_resource_key,
            allocation_id=allocation_id,
            purpose="model-replica-realization",
            host=request.endpoint_host,
            authority=snapshot,
            candidates=self._endpoint_candidates,
            probe=self._endpoint_probe,
            owner_scope=request.scope,
            scope_generation=scope_generation,
            scope_lease_id=scope_lease_id,
        )

    def _reconcile_replica(
        self,
        request: ModelReplicaPoolRequest,
        index: int,
        *,
        excluded_gpus: frozenset[tuple[str, str]] = frozenset(),
    ) -> tuple[
        object,
        NoetriumUnit,
        NoetriumUnit,
        NoetriumUnit,
        ModelDesiredDeployment,
        ModelDeploymentGeneration,
        ModelDeploymentStatus,
    ]:
        identity = request.runtime_identity_digest
        topology = self._topology(identity, index)
        compute_key, endpoint_key, service_key = self._resource_keys(
            identity,
            index,
        )
        holder_key = "model-runtime:" + identity
        owner_generation, owner_scope_lease_id = (
            self._authority.scope_ownership_cut(request.scope)
        )
        before = self._authority.snapshot_for_holder(holder_key)
        preexisting_closure = any(
            before.claims_for(key)
            or before.tickets_for(key)
            or before.binding_for(key) is not None
            for key in (compute_key, endpoint_key, service_key)
        )
        hosts = self._compute_inventory.list_hosts(scope=request.scope)
        if not hosts:
            raise ComputePlacementUnavailable(request.effective_compute)
        self._authority.declare_capacity(compute_capacity(hosts))

        def compute_candidates(
            snapshot: AuthoritySnapshot,
            generation: int,
        ) -> tuple[NoetriumUnit, ...]:
            return compute_claim_candidates(
                resource_key=compute_key,
                holder_key=holder_key,
                generation=generation,
                consumer_resource_key=service_key,
                requirement=request.effective_compute,
                hosts=hosts,
                authority=snapshot,
                placement_scope=request.scope,
                gpu_runtime=self._gpu_runtime.snapshot(),
                host_runtime=self._host_runtime.snapshot(),
                excluded_gpus=excluded_gpus,
                owner_scope=request.scope,
                scope_generation=owner_generation.generation,
                scope_lease_id=owner_scope_lease_id,
            )

        def endpoint_candidates(
            snapshot: AuthoritySnapshot,
            generation: int,
        ) -> tuple[NoetriumUnit, ...]:
            return self._endpoint_claims(
                snapshot=snapshot,
                generation=generation,
                resource_key=endpoint_key,
                holder_key=holder_key,
                consumer_resource_key=service_key,
                allocation_id=endpoint_key,
                request=request,
                scope_generation=owner_generation.generation,
                scope_lease_id=owner_scope_lease_id,
            )

        def service_candidates(
            _snapshot: AuthoritySnapshot,
            generation: int,
        ) -> tuple[NoetriumUnit, ...]:
            attrs = {
                "kind": "model-service",
                "runtime_identity": identity,
                "replica_index": index,
            }
            return (
                resource_claim(
                    claim_id="model-service:"
                    + canonical_digest(
                        {
                            "resource_key": service_key,
                            "generation": generation,
                            "holder_key": holder_key,
                            "attributes": attrs,
                        }
                    ),
                    resource_key=service_key,
                    holder_key=holder_key,
                    generation=generation,
                    owner_scope=request.scope,
                    scope_generation=owner_generation.generation,
                    scope_lease_id=owner_scope_lease_id,
                    owner_lease_id=None,
                    attributes=attrs,
                ),
            )

        def service_spec(
            snapshot: AuthoritySnapshot,
        ) -> ResourceRealizationSpec:
            generation = snapshot.generation_for(service_key)
            if generation is None:
                raise RuntimeError(
                    "model service realization lacks Authority generation"
                )
            compute = _single_current_claim(snapshot, compute_key)
            endpoint = _single_current_claim(snapshot, endpoint_key)
            deployment = self._deployment(
                request,
                replica_index=index,
                deployment_id=model_resource_deployment_id(
                    service_key,
                    generation.generation,
                ),
                service_resource_key=service_key,
                compute=compute,
                endpoint=endpoint,
            )
            return ResourceRealizationSpec(
                ModelServicePhysicalProvider.provider_kind,
                model_realization_parameters(deployment),
            )

        try:
            snapshot = self._authority.reconcile(
                topology,
                claim_candidates={
                    "compute": compute_candidates,
                    "endpoint": endpoint_candidates,
                    "service": service_candidates,
                },
                realization_specs={"service": service_spec},
                providers={
                    ModelServicePhysicalProvider.provider_kind: self._provider
                },
            )
        except BaseException:
            # Never destroy a pre-existing warm/recoverable Authority closure
            # because one attachment attempt observed a transient failure. Its
            # PREPARED/BOUND state is durable recovery truth. Only a closure
            # that was absent before this call AND has no foreign admitted
            # consumers may be rolled back. Another producer may have joined
            # after our initial snapshot; its lease forbids us from deleting
            # a now-shared physical realization during error compensation.
            active_consumers = self._authority.active_leases(
                self._consumer_resource_key(identity)
            )
            if preexisting_closure or len(active_consumers) > 1:
                raise
            try:
                self._authority.reconcile(
                    topology,
                    claim_candidates={},
                    realization_specs={},
                    providers={
                        ModelServicePhysicalProvider.provider_kind: self._provider
                    },
                    desired_resource_ids=frozenset(),
                )
            except BaseException as cleanup_error:
                raise BaseExceptionGroup(
                    "new model replica realization failed with pending Authority cleanup",
                    [cleanup_error],
                )
            raise

        compute = _single_current_claim(snapshot, compute_key)
        endpoint = _single_current_claim(snapshot, endpoint_key)
        service = _single_current_claim(snapshot, service_key)
        service_generation = snapshot.generation_for(service_key)
        if service_generation is None:
            raise RuntimeError("model service lost Authority generation")
        deployment_id = model_resource_deployment_id(
            service_key,
            service_generation.generation,
        )
        deployment = self._catalog.deployment(deployment_id)
        generation = self._deployment_runtime.generation(deployment_id)
        status = self._deployment_runtime.status(deployment_id)
        if status.runtime_state is not ModelRuntimeState.RUNNING:
            raise RuntimeError(
                "Authority-converged model service is not running: "
                f"{deployment_id}:{status.runtime_state.value}:{status.detail}"
            )
        return (
            topology,
            compute,
            endpoint,
            service,
            deployment,
            generation,
            status,
        )

    @staticmethod
    def _deployment(
        request: ModelReplicaPoolRequest,
        *,
        replica_index: int,
        deployment_id: str,
        service_resource_key: str,
        compute: NoetriumUnit,
        endpoint: NoetriumUnit,
    ) -> ModelDesiredDeployment:
        compute_attrs = _claim_attributes(compute, "compute")
        endpoint_attrs = _claim_attributes(endpoint, "network-endpoint")
        if not deployment_id.strip() or not service_resource_key.strip():
            raise ValueError("model Authority deployment identity is required")
        stack = request.model_stack
        launch = model_stack_launch_settings(stack)
        common = dict(
            deployment_id=deployment_id,
            scope=request.scope,
            model_id=request.model_id,
            container_digest=stack.runtime.container_digest,
            cwd=request.cwd,
            host=str(endpoint_attrs["host"]),
            port=int(endpoint_attrs["port"]),
            tensor_parallel=stack.tensor_parallel,
            gpu_devices=tuple(str(v) for v in compute_attrs.get("gpu_ids", ())),
            gpu_memory_reservation_bytes=tuple(
                int(v)
                for v in compute_attrs.get(
                    "gpu_memory_reservation_bytes",
                    (),
                )
            ),
            extra_args=launch.engine_args,
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
        return replace(
            spec,
            environment=tuple(
                sorted((*spec.environment, *launch.environment))
            ),
            desired_state=ModelDesiredState.RUNNING,
            tags=tuple(
                sorted(
                    {
                        "auto-managed",
                        f"replica-index:{replica_index:03d}",
                        f"model-stack:{stack.digest()}",
                        f"runtime-identity:{request.runtime_identity_digest}",
                        f"resource-key:{service_resource_key}",
                        *request.tags,
                    }
                )
            ),
        )

    @staticmethod
    def _placement(
        index: int,
        compute: NoetriumUnit,
        endpoint: NoetriumUnit,
        service: NoetriumUnit,
        spec: ModelDesiredDeployment,
        generation: ModelDeploymentGeneration,
        status: ModelDeploymentStatus,
    ) -> ModelReplicaPlacement:
        compute_attrs = _claim_attributes(compute, "compute")
        endpoint_attrs = _claim_attributes(endpoint, "network-endpoint")
        _claim_attributes(service, "model-service")
        return ModelReplicaPlacement(
            replica_index=index,
            deployment_id=spec.deployment_id,
            host_id=str(compute_attrs["host_id"]),
            gpu_ids=tuple(str(v) for v in compute_attrs.get("gpu_ids", ())),
            gpu_memory_reservation_bytes=tuple(
                int(v)
                for v in compute_attrs.get(
                    "gpu_memory_reservation_bytes",
                    (),
                )
            ),
            endpoint_host=str(endpoint_attrs["host"]),
            endpoint_port=int(endpoint_attrs["port"]),
            compute_resource_key=claim_field(compute, "resource_key"),
            endpoint_resource_key=claim_field(endpoint, "resource_key"),
            service_resource_key=claim_field(service, "resource_key"),
            compute_claim_id=claim_field(compute, "claim_id"),
            endpoint_claim_id=claim_field(endpoint, "claim_id"),
            service_claim_id=claim_field(service, "claim_id"),
            deployment=spec,
            generation=generation,
            status=status,
        )

    def _materialize_owner(
        self,
        request: ModelReplicaPoolRequest,
    ) -> _ModelReplicaPoolOwner:
        target = request.replica_count
        placements: list[ModelReplicaPlacement] = []
        topologies: list[object] = []
        index = 0
        while target is None or index < target:
            try:
                (
                    topology,
                    compute,
                    endpoint,
                    service,
                    spec,
                    generation,
                    status,
                ) = self._reconcile_replica(request, index)
            except ComputePlacementUnavailable:
                if target is None and placements:
                    break
                raise
            placements.append(
                self._placement(
                    index,
                    compute,
                    endpoint,
                    service,
                    spec,
                    generation,
                    status,
                )
            )
            topologies.append(topology)
            index += 1
        if not placements:
            raise ComputePlacementUnavailable(request.effective_compute)
        owner = _ModelReplicaPoolOwner(
            ModelReplicaPoolReport(
                request_digest=canonical_digest(request),
                placements=tuple(placements),
            ),
            deployment_runtime=self._deployment_runtime,
            authority=self._authority,
            provider=self._provider,
            topologies=tuple(topologies),
        )
        owner.assert_healthy()
        return owner

    def borrow_existing(
        self,
        request: ModelReplicaPoolRequest,
        *,
        expected_replica_count: int | None = None,
    ) -> ModelReplicaPoolLease | None:
        """Borrow an exact, already-owned fleet without launching new replicas.

        Bootstrap uses Authority-adaptive replica_count=None; a later refresh
        knows its observed cardinality. Both must share the same physical owner
        when the existing fleet satisfies the exact certified topology. The
        original identity and cross-process consumer-retirement fence are
        retained; no compatibility identity, extra Authority or new Effect.
        """
        if not isinstance(request, ModelReplicaPoolRequest):
            raise TypeError("model replica pool requires ModelReplicaPoolRequest")
        if expected_replica_count is not None and (
            type(expected_replica_count) is not int or expected_replica_count <= 0
        ):
            raise ValueError("expected_replica_count must be positive")
        identity = request.runtime_identity_digest
        with self._identity_lock(identity):
            with self._lock:
                if self._closing or self._closed:
                    raise RuntimeError("model replica pool is closing")
                owner = self._owners.get(identity)
                if owner is None or (
                    expected_replica_count is not None
                    and len(owner.report.placements) != expected_replica_count
                ):
                    return None
            # Acquire the Authority consumer lease before checking liveness;
            # otherwise concurrent retirement could race the observation.
            reservation = self._reserve_consumer(identity)
            try:
                with self._lock:
                    if self._closing or self._closed:
                        raise RuntimeError("model replica pool is closing")
                    owner = self._owners.get(identity)
                    if owner is None:
                        return None
                    if (expected_replica_count is not None
                            and len(owner.report.placements) != expected_replica_count):
                        return None
                    owner.assert_healthy()
                    result = self._consumer(owner, identity, reservation=reservation)
                    reservation = None
                    return result
            finally:
                if reservation is not None:
                    _id, authority_lease, guard = reservation
                    try:
                        guard.close()
                    finally:
                        self._authority.release_lease(authority_lease)

    def ensure(
        self,
        request: ModelReplicaPoolRequest,
    ) -> ModelReplicaPoolLease:
        if not isinstance(request, ModelReplicaPoolRequest):
            raise TypeError("model replica pool requires ModelReplicaPoolRequest")
        identity = request.runtime_identity_digest
        identity_lock = self._identity_lock(identity)
        with identity_lock:
            with self._lock:
                if self._closed:
                    raise RuntimeError("model replica pool is closed")
                if self._closing:
                    raise RuntimeError("model replica pool is closing")
            # Linearize with the cross-process retirement fence BEFORE any
            # health check or physical reconciliation. A reservation is held
            # continuously until the final consumer owns the same lease.
            reservation = self._reserve_consumer(identity)
            try:
                with self._lock:
                    owner = self._owners.get(identity)
                    if owner is not None:
                        owner.assert_healthy()
                        consumer = self._consumer(
                            owner, identity, reservation=reservation,
                        )
                        reservation = None
                        return consumer
                    self._materializations += 1
                try:
                    owner = self._materialize_owner(request)
                finally:
                    with self._lock:
                        self._materializations -= 1
                        self._changed.notify_all()
                with self._lock:
                    if self._closing or self._closed:
                        owner.detach()
                        raise RuntimeError(
                            "model replica pool closed during materialization"
                        )
                    self._owners[identity] = owner
                    consumer = self._consumer(
                        owner, identity, reservation=reservation,
                    )
                    reservation = None
                    return consumer
            finally:
                if reservation is not None:
                    _id, authority_lease, guard = reservation
                    try:
                        guard.close()
                    finally:
                        self._authority.release_lease(authority_lease)
    def _wait_materializations(self) -> None:
        while self._materializations:
            self._changed.wait()

    def detach_all(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closing = True
            self._wait_materializations()
            leases = tuple(self._leases.values())
            owners = tuple(self._owners.values())
        for lease in leases:
            lease.close()
        for owner in owners:
            owner.detach()
        with self._lock:
            self._owners.clear()
            self._closed = True

    def close_all(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closing = True
            self._wait_materializations()
            leases = tuple(self._leases.values())
            owners = tuple(self._owners.items())
        for lease in leases:
            lease.close()
        errors: list[BaseException] = []
        for identity, owner in owners:
            try:
                if not self._retire_identity(identity):
                    raise RuntimeError(
                        "cannot retire model realization with active consumers: "
                        + identity
                    )
                owner.detach()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise BaseExceptionGroup(
                "model replica pool retirement failed",
                errors,
            )
        with self._lock:
            self._owners.clear()
            self._closed = True

    def _authority_realization_indices(self, identity: str) -> tuple[int, ...]:
        snapshot = self._authority.snapshot_for_holder(
            "model-runtime:" + identity
        )
        values: set[int] = set()
        for claim in snapshot.claims:
            attrs = dict(claim_field(claim, "attributes") or {})
            if (
                attrs.get("kind") != "model-service"
                or attrs.get("runtime_identity") != identity
            ):
                continue
            index = attrs.get("replica_index")
            if type(index) is not int or index < 0:
                raise RuntimeError(
                    "model service Authority claim has invalid replica index"
                )
            values.add(index)
        return tuple(sorted(values))

    def _retire_identity(self, identity: str) -> bool:
        """Retire one physical model identity only under a zero-consumer fence.

        The per-identity lock serializes this process's ensure/retire paths.  The
        Authority consumer fence is the cross-process linearization point: it
        atomically proves that the current consumer generation has no live
        leases and advances admission before any physical effect can be removed.
        No caller is allowed to bypass this primitive.
        """

        if type(identity) is not str or not identity.strip():
            raise ValueError("model runtime identity is required")
        identity = identity.strip()
        identity_lock = self._identity_lock(identity)
        with identity_lock:
            with self._lock:
                owner = self._owners.get(identity)
                if owner is not None and any(
                    lease._owner is owner and not lease.closed
                    for lease in self._leases.values()
                ):
                    return False

            indices = self._authority_realization_indices(identity)
            if not indices:
                return False
            consumer_key = self._consumer_resource_key(identity)
            self._authority.ensure_generation(consumer_key)
            try:
                gate = self._authority.fence_if_no_live_leases(
                    consumer_key,
                    holder_key="model-runtime-retirement:" + identity,
                )
            except RuntimeError as exc:
                if str(exc).startswith(
                    "resource generation still has live consumers:"
                ):
                    return False
                raise

            try:
                errors: list[BaseException] = []
                for index in reversed(indices):
                    try:
                        self._authority.reconcile(
                            self._topology(identity, index),
                            claim_candidates={},
                            realization_specs={},
                            providers={
                                ModelServicePhysicalProvider.provider_kind: self._provider
                            },
                            desired_resource_ids=frozenset(),
                        )
                    except BaseException as exc:
                        errors.append(exc)
                if errors:
                    raise BaseExceptionGroup(
                        "model realization Authority retirement failed",
                        errors,
                    )
                return True
            finally:
                self._authority.release_claim(claim_field(gate, "claim_id"))

    def retire(self, request: ModelReplicaPoolRequest) -> bool:
        if not isinstance(request, ModelReplicaPoolRequest):
            raise TypeError("model replica retirement requires request")
        identity = request.runtime_identity_digest
        identity_lock = self._identity_lock(identity)
        with identity_lock:
            with self._lock:
                owner = self._owners.get(identity)
                if owner is not None:
                    consumers = tuple(
                        lease.consumer_lease_id
                        for lease in self._leases.values()
                        if lease._owner is owner and not lease.closed
                    )
                    if consumers:
                        raise RuntimeError(
                            "cannot retire model realization with active consumers"
                        )
            retired = self._retire_identity(identity)
            with self._lock:
                local = self._owners.pop(identity, None)
                if local is not None:
                    local._closed = True
            return retired

    def _exclusive_runtime_fabric_consumer(self) -> bool:
        key = self._runtime_fabric_resource_key
        own = self._runtime_fabric_consumer_lease_id
        if key is None or own is None:
            return False
        leases = self._authority.active_leases(key)
        own_rows = tuple(row for row in leases if lease_field(row, "lease_id") == own)
        return len(own_rows) == 1 and all(
            lease_field(row, "lease_id") == own for row in leases
        )
    def reconcile_absent_warm_realizations(self) -> tuple[str, ...]:
        """Retire Authority state only for model services proven physically absent.

        This is crash recovery, not capacity reclamation: an absent physical
        service cannot be protected by another consumer.  Unobservable or still
        existing services are left untouched.
        """

        snapshot = self._authority.snapshot_for_claim_kinds(
            frozenset({"model-service"})
        )
        identities: dict[str, str] = {}
        for claim in snapshot.claims:
            attrs = dict(claim_field(claim, "attributes") or {})
            identity = attrs.get("runtime_identity")
            if attrs.get("kind") != "model-service" or not isinstance(identity, str):
                continue
            binding = snapshot.binding_for(claim_field(claim, "resource_key"))
            if binding is None:
                continue
            observation = self._provider.observe(binding_field(binding, "physical_identity"))
            if observation_field(observation, "exists"):
                continue
            identities.setdefault(identity, claim_field(claim, "resource_key"))

        retired: list[str] = []
        for identity in sorted(identities):
            identity_lock = self._identity_lock(identity)
            with identity_lock:
                # Re-observe one transactionally consistent holder-local
                # Authority cut. All compute/endpoint/service claims for this
                # runtime identity share the same holder key.
                current = self._authority.snapshot_for_holder(
                    "model-runtime:" + identity
                )
                service_claims = tuple(
                    claim
                    for claim in current.claims
                    if dict(claim_field(claim, "attributes") or {}).get("kind") == "model-service"
                    and dict(claim_field(claim, "attributes") or {}).get("runtime_identity") == identity
                )
                if not service_claims:
                    continue
                all_absent = True
                for claim in service_claims:
                    binding = current.binding_for(claim_field(claim, "resource_key"))
                    if binding is None:
                        all_absent = False
                        break
                    if observation_field(self._provider.observe(binding_field(binding, "physical_identity")), "exists"):
                        all_absent = False
                        break
                if not all_absent:
                    continue
                if self._retire_identity(identity):
                    with self._lock:
                        owner = self._owners.pop(identity, None)
                        if owner is not None:
                            owner._closed = True
                    retired.append(identity)
        return tuple(retired)

    def reclaim_stale_warm_realization(self, runtime_identity: str) -> bool:
        """Retire one exact unleased warm identity when this process is sole fabric consumer."""

        if type(runtime_identity) is not str or not runtime_identity.strip():
            raise ValueError("stale warm runtime identity is required")
        identity = runtime_identity.strip()
        snapshot = self._authority.snapshot_for_holder(
            "model-runtime:" + identity
        )
        if not any(
            dict(claim_field(claim, "attributes") or {}).get("kind") == "model-service"
            and dict(claim_field(claim, "attributes") or {}).get("runtime_identity") == identity
            for claim in snapshot.claims
        ):
            return False
        return self._retire_unleased_warm_identity(identity)

    def _warm_reclamation_state(
        self,
        *,
        protected_runtime_identities: frozenset[str],
    ) -> tuple[dict[str, int], frozenset[str]]:
        with self._lock:
            active_owner_ids = {
                id(lease._owner)
                for lease in self._leases.values()
                if not lease.closed
            }
            active_local = frozenset(
                identity
                for identity, owner in self._owners.items()
                if id(owner) in active_owner_ids
            )

        snapshot = self._authority.snapshot_for_claim_kinds(
            frozenset({"compute", "model-service"})
        )
        reserved_vram_by_consumer: dict[str, int] = {}
        for resource_claim in snapshot.claims:
            resource_attrs = dict(claim_field(resource_claim, "attributes") or {})
            if resource_attrs.get("kind") != "compute":
                continue
            consumer = resource_attrs.get("consumer_resource_key")
            if not isinstance(consumer, str) or not consumer:
                continue
            reserved_vram_by_consumer[consumer] = (
                reserved_vram_by_consumer.get(consumer, 0)
                + sum(
                    int(value)
                    for value in resource_attrs.get(
                        "gpu_memory_reservation_bytes",
                        (),
                    )
                )
            )

        binding_by_resource = {
            binding_field(binding, "resource_key"): binding
            for binding in snapshot.bindings
        }
        by_identity: dict[str, int] = {}
        capabilities: dict[str, _WarmRuntimeCapability] = {}
        ambiguous_capabilities: set[str] = set()
        for claim in snapshot.claims:
            attrs = dict(claim_field(claim, "attributes") or {})
            if attrs.get("kind") != "model-service":
                continue
            identity = attrs.get("runtime_identity")
            if not isinstance(identity, str):
                continue

            binding = binding_by_resource.get(claim_field(claim, "resource_key"))
            if binding is not None:
                try:
                    spec = self._catalog.deployment(
                        physical_field(binding_field(binding, "physical_identity"), "physical_id")
                    )
                except KeyError:
                    spec = None
                if spec is not None:
                    status = self._deployment_runtime.status(
                        spec.deployment_id
                    )
                    if status.runtime_state is ModelRuntimeState.RUNNING:
                        capability = _warm_runtime_capability(spec)
                        if capability is not None:
                            existing = capabilities.get(identity)
                            if existing is None:
                                capabilities[identity] = capability
                            elif existing != capability:
                                ambiguous_capabilities.add(identity)

            if (
                identity in active_local
                or identity in protected_runtime_identities
                or self._authority.active_leases(
                    self._consumer_resource_key(identity)
                )
            ):
                continue
            by_identity[identity] = (
                by_identity.get(identity, 0)
                + reserved_vram_by_consumer.get(claim_field(claim, "resource_key"), 0)
            )

        for identity in ambiguous_capabilities:
            capabilities.pop(identity, None)
        reclaimable = frozenset(by_identity)
        comparable_reclaimable = frozenset(
            identity
            for identity in reclaimable
            if identity in capabilities
        )
        dominated = _dominated_warm_runtime_identities(
            capabilities,
            reclaimable=comparable_reclaimable,
        )
        return by_identity, dominated

    def _retire_unleased_warm_identity(self, identity: str) -> bool:
        if not self._retire_identity(identity):
            return False
        with self._lock:
            local_owner = self._owners.pop(identity, None)
            if local_owner is not None:
                local_owner.detach()
        return True

    def reclaim_one_stale_warm_realization(
        self,
        *,
        protected_runtime_identities: frozenset[str] = frozenset(),
    ) -> str | None:
        if type(protected_runtime_identities) is not frozenset or any(
            type(value) is not str for value in protected_runtime_identities
        ):
            raise TypeError("protected identities must be frozenset[str]")

        by_identity, dominated = self._warm_reclamation_state(
            protected_runtime_identities=protected_runtime_identities,
        )
        if not by_identity:
            return None
        candidates = dominated if dominated else frozenset(by_identity)

        # Strictly redundant warm contexts retire before generic pressure
        # reclamation. Within the chosen class, return the most reserved VRAM.
        for identity in sorted(
            candidates,
            key=lambda value: (-by_identity[value], value),
        ):
            if self._retire_unleased_warm_identity(identity):
                return identity
        return None

    def reclaim_dominated_warm_realizations(
        self,
        *,
        protected_runtime_identities: frozenset[str] = frozenset(),
    ) -> tuple[str, ...]:
        """Retire every unleased warm runtime made redundant by a stronger one."""

        if type(protected_runtime_identities) is not frozenset or any(
            type(value) is not str for value in protected_runtime_identities
        ):
            raise TypeError("protected identities must be frozenset[str]")

        retired: list[str] = []
        while True:
            by_identity, dominated = self._warm_reclamation_state(
                protected_runtime_identities=(
                    protected_runtime_identities | frozenset(retired)
                ),
            )
            if not dominated:
                break
            progressed = False
            for identity in sorted(
                dominated,
                key=lambda value: (-by_identity[value], value),
            ):
                if self._retire_unleased_warm_identity(identity):
                    retired.append(identity)
                    progressed = True
                    break
            if not progressed:
                break
        return tuple(retired)



__all__ = [
    "LocalModelReplicaPoolRuntime",
    "ModelReplicaPlacement",
    "ModelReplicaPoolLease",
    "ModelReplicaPoolReport",
    "ModelReplicaPoolRequest",
]
