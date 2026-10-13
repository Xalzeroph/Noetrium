from __future__ import annotations

import math

from noetrium_platform.capabilities.model.serving.api.admission import ModelAdmissionRegistryPort
from noetrium_platform.capabilities.model.serving.api.qualified_deployment import QualifiedDeploymentManifest
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    AdaptiveModelEndpointPoolPort,
    AsyncJsonHttpTransportPort,
    ModelEndpointReplicaSet,
    ModelEndpointRoute,
    OperationalModelEndpointReplica,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    PooledModelHttpTransport,
    NativeModelProviderEndpoint,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    AdaptiveModelEndpointPool,
)
from noetrium_platform.foundation.kernel.kernel import (
    AdaptiveServiceWindowPolicy,
)
from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.foundation.kernel.concurrency.scheduling.api import SchedulingAuthorityPort


def build_runtime_canary_endpoint(
    deployment: QualifiedDeploymentManifest,
    route: ModelEndpointRoute,
    *,
    task_group: TaskGroupPort,
    admission_registry: ModelAdmissionRegistryPort,
    scheduling_authority: SchedulingAuthorityPort,
    api_key: str = "",
    timeout_s: float | None = None,
    transport: AsyncJsonHttpTransportPort | None = None,
    observers: tuple[object, ...] = (),
) -> AdaptiveModelEndpointPoolPort:
    """Build the universal adaptive dispatch machine for pre-closure canaries."""
    generation = deployment.digest()
    if route.deployment_id != deployment.deployment_id:
        raise ValueError("runtime canary route deployment identity drift")
    if route.deployment_generation != generation:
        raise ValueError("runtime canary route generation drift")
    if timeout_s is not None:
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
            raise TypeError("runtime canary endpoint timeout_s must be numeric")
        if not math.isfinite(float(timeout_s)) or timeout_s <= 0:
            raise ValueError("runtime canary endpoint timeout_s must be positive and finite")

    envelope = deployment.certificate.resource_envelope
    request_capacity = envelope.max_qualified_concurrency
    qualified_capacity = request_capacity + (
        envelope.latency_isolation_concurrency
        if envelope.preemptive_latency_isolation else 0
    )
    owns_transport = transport is None
    if transport is None:
        transport = PooledModelHttpTransport(
            max_connections=qualified_capacity,
            max_keepalive_connections=qualified_capacity,
        )

    effective_route = ModelEndpointRoute(
        deployment_id=deployment.deployment_id,
        deployment_generation=generation,
        base_url=route.base_url,
        completion_path=route.completion_path,
        timeout_s=route.timeout_s if timeout_s is None else float(timeout_s),
    )
    admission = admission_registry.controller_for(
        deployment_id=deployment.deployment_id,
        deployment_generation=generation,
        qualified_capacity=qualified_capacity,
    )

    def endpoint_factory(_binding):
        return NativeModelProviderEndpoint(
            route=effective_route,
            transport=transport,
            task_group=task_group,
            admission=admission,
            api_key=api_key,
            observers=observers,
            owns_transport=owns_transport,
        )

    preferred = deployment.certificate.resource_envelope.preferred_operating_concurrency
    initial_limit = max(1, min(
        qualified_capacity,
        qualified_capacity if preferred is None else preferred,
    ))
    # Adaptive startup is a scheduling prior, never a physical qualification.
    admission.qualify_continuity(request_capacity)
    return AdaptiveModelEndpointPool(
        ModelEndpointReplicaSet((
            OperationalModelEndpointReplica(effective_route, qualified_capacity),
        )),
        endpoint_factory,
        scheduling_authority=scheduling_authority,
        physical_continuity_controllers={deployment.deployment_id: admission},
        adaptive_window_policy=AdaptiveServiceWindowPolicy(
            min_limit=1,
            start_limit=initial_limit,
        ),
    )


__all__ = ["build_runtime_canary_endpoint"]
