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
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    AdaptiveModelEndpointPool,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    NativeModelProviderEndpoint,
    PooledModelHttpTransport,
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

    admission = admission_registry.controller_for(
        deployment_id=binding.deployment_id,
        deployment_generation=binding.deployment_generation,
        qualified_capacity=binding.max_admitted_concurrency,
    )
    owned_transport = transport is None
    resolved_transport = (
        PooledModelHttpTransport(
            max_connections=binding.max_admitted_concurrency,
            max_keepalive_connections=binding.max_admitted_concurrency,
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
    transport: AsyncJsonHttpTransportPort | None = None,
) -> AdaptiveModelEndpointPool:
    """Bind one frozen endpoint replica set to the single adaptive dispatch machine."""

    if not isinstance(replica_set, ModelEndpointReplicaSet):
        raise TypeError("adaptive endpoint pool requires ModelEndpointReplicaSet")
    if replica_set.qualified:
        def factory(binding):
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
            )
            owned_transport = transport is None
            resolved_transport = (
                PooledModelHttpTransport(
                    max_connections=replica.capacity,
                    max_keepalive_connections=replica.capacity,
                )
                if transport is None
                else transport
            )
            return NativeModelProviderEndpoint(
                route=replica.route,
                transport=resolved_transport,
                task_group=task_group,
                admission=admission,
                api_key=api_key,
                observers=observers,
                owns_transport=owned_transport,
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

    return AdaptiveModelEndpointPool(
        replica_set,
        factory,
        selection_policy=selection_policy,
        pressure_observer=pressure_observer,
        pressure_task_group=(
            task_group if pressure_observer is not None else None
        ),
    )


__all__ = [
    "build_adaptive_model_endpoint_pool",
    "build_qualified_model_endpoint",
]
