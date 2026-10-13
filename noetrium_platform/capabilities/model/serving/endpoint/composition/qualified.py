from __future__ import annotations

from noetrium_platform.capabilities.model.serving.api.admission import ModelAdmissionRegistryPort
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    AsyncJsonHttpTransportPort,
    AsyncTextHttpTransportPort,
    ModelEndpointReplicaSet,
    ModelEndpointPort,
    ModelEndpointRoute,
    QualifiedModelEndpointBinding,
    ModelEndpointReplicaSelectionPolicyPort,
)
from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.foundation.kernel.concurrency.scheduling.api import SchedulingAuthorityPort
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    AdaptiveModelEndpointPool,
    ModelRequestRetryPolicy,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    NativeModelProviderEndpoint,
    PooledModelHttpTransport,
    PooledModelHttpTransportOwner,
    VllmRuntimePressureObserver,
)


def build_qualified_model_endpoint(
    binding: QualifiedModelEndpointBinding,
    *,
    api_key: str = "",
    timeout_s: float | None = None,
    task_group: TaskGroupPort,
    admission_registry: ModelAdmissionRegistryPort,
    observers: tuple[object, ...] = (),
    transport: AsyncJsonHttpTransportPort | None = None,
) -> ModelEndpointPort:
    """Materialize one endpoint from a platform-qualified binding."""

    priority_return_headroom = (
        binding.latency_isolation_concurrency
        if binding.preemptive_latency_isolation
        else 0
    )
    wire_capacity = (
        binding.max_admitted_concurrency
        + priority_return_headroom
    )
    admission = admission_registry.controller_for(
        deployment_id=binding.deployment_id,
        deployment_generation=binding.deployment_generation,
        qualified_capacity=wire_capacity,
        # Continuity is a lifetime ownership/affinity entitlement, not a
        # latency-SLO lane.  Its hard ceiling therefore follows the measured
        # qualified request capacity.  Preferred/isolated concurrency remains
        # a runtime scheduling prior only.
        continuity_capacity=binding.max_admitted_concurrency,
    )
    owned_transport = transport is None
    resolved_transport = (
        PooledModelHttpTransport(
            max_connections=wire_capacity,
            max_keepalive_connections=wire_capacity,
        )
        if transport is None
        else transport
    )
    return NativeModelProviderEndpoint(
        route=ModelEndpointRoute(
            deployment_id=binding.deployment_id,
            deployment_generation=binding.deployment_generation,
            base_url=binding.base_url,
            completion_path=binding.completion_path,
            timeout_s=binding.timeout_s if timeout_s is None else timeout_s,
        ),
        transport=resolved_transport,
        api_key=api_key,
        task_group=task_group,
        admission=admission,
        observers=observers,
        owns_transport=owned_transport,
    )


__all__ = [
    "build_qualified_model_endpoint",
]


def build_adaptive_model_endpoint_pool(
    replica_set: ModelEndpointReplicaSet,
    *,
    api_key: str = "",
    timeout_s: float | None = None,
    task_group: TaskGroupPort,
    admission_registry: ModelAdmissionRegistryPort,
    observers: tuple[object, ...] = (),
    selection_policy: ModelEndpointReplicaSelectionPolicyPort | None = None,
    retry_policy: ModelRequestRetryPolicy | None = None,
    scheduling_authority: SchedulingAuthorityPort,
    transport: AsyncJsonHttpTransportPort | None = None,
) -> AdaptiveModelEndpointPool:
    """Bind one frozen endpoint replica set to the single adaptive dispatch machine."""

    if not isinstance(replica_set, ModelEndpointReplicaSet):
        raise TypeError("adaptive endpoint pool requires ModelEndpointReplicaSet")
    physical_controllers = {}
    # A single pool-owned transport shares HTTP connection reuse across
    # replicas and exposes the same vLLM pressure evidence to scheduling.
    # Endpoint leases still belong exclusively to the Resource Authority.
    owned_transport = None
    if transport is None:
        wire_capacity = sum(
            (
                binding.max_admitted_concurrency + (
                    binding.latency_isolation_concurrency
                    if binding.preemptive_latency_isolation else 0)
            ) if replica_set.qualified else binding.capacity
            for binding in replica_set.members
        )
        # Keep a free HTTP slot for each vLLM pressure probe even when all
        # qualified generation slots are occupied. These are transport slots,
        # not additional physical model admission permits.
        probe_slots = (
            len(replica_set.members)
            if replica_set.qualified and all(
                member.model.engine.strip().lower() == "vllm"
                for member in replica_set.members
            ) else 0
        )
        transport = PooledModelHttpTransport(
            max_connections=wire_capacity + probe_slots,
            max_keepalive_connections=wire_capacity + probe_slots,
        )
        owned_transport = PooledModelHttpTransportOwner(transport, task_group)
    if replica_set.qualified:
        def factory(binding):
            physical_controllers[binding.deployment_id] = admission_registry.controller_for(
                deployment_id=binding.deployment_id,
                deployment_generation=binding.deployment_generation,
                qualified_capacity=(
                    binding.max_admitted_concurrency + (
                        binding.latency_isolation_concurrency
                        if binding.preemptive_latency_isolation else 0
                    )
                ),
                # Persistent flows may coexist up to the measured safe physical
                # ceiling; the adaptive request window governs active pressure.
                continuity_capacity=binding.max_admitted_concurrency,
            )
            return build_qualified_model_endpoint(
                binding, api_key=api_key, timeout_s=timeout_s,
                task_group=task_group, admission_registry=admission_registry,
                observers=observers,
                transport=transport,
            )
    else:
        def factory(replica):
            admission = admission_registry.controller_for(
                deployment_id=replica.deployment_id,
                deployment_generation=replica.deployment_generation,
                qualified_capacity=replica.capacity,
                continuity_capacity=replica.capacity,
            )
            physical_controllers[replica.deployment_id] = admission
            resolved_transport = transport
            return NativeModelProviderEndpoint(
                route=replica.route,
                transport=resolved_transport,
                task_group=task_group,
                admission=admission,
                api_key=api_key,
                observers=observers,
                owns_transport=False,
            )

    pressure_observer = None
    if (
        replica_set.qualified
        and transport is not None
        and isinstance(transport, AsyncTextHttpTransportPort)
        and all(
            binding.model.engine.strip().lower() == "vllm"
            for binding in replica_set.members
        )
    ):
        pressure_observer = VllmRuntimePressureObserver(transport)

    try:
        return AdaptiveModelEndpointPool(
            replica_set,
            factory,
            selection_policy=selection_policy,
            retry_policy=retry_policy,
            scheduling_authority=scheduling_authority,
            physical_continuity_controllers=physical_controllers,
            pressure_observer=pressure_observer,
            pressure_task_group=(
                task_group if pressure_observer is not None else None
            ),
            owned_transport_close=(
                None if owned_transport is None else owned_transport.close
            ),
        )
    except BaseException as exc:
        # A failed pool constructor has no lifetime owner to close the shared
        # HTTP transport; preserve both the original failure and close failure.
        if owned_transport is not None:
            try:
                owned_transport.close()
            except BaseException as close_exc:
                raise BaseExceptionGroup(
                    "model endpoint pool construction and transport close failed",
                    [exc, close_exc],
                ) from exc
        raise


__all__ = [
    "build_adaptive_model_endpoint_pool",
    "build_qualified_model_endpoint",
]
