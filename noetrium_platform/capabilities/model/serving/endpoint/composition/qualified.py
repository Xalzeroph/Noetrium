from __future__ import annotations

from noetrium_platform.capabilities.model.serving.api import ModelAdmissionRegistryPort
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    OperationalModelEndpointReplicaSet,
    QualifiedModelEndpointReplicaSet,
    ModelEndpointPort,
    ModelEndpointRoute,
    QualifiedModelEndpointBinding,
    ModelEndpointReplicaSelectionPolicyPort,
)
from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    AdaptiveOperationalModelEndpointPool,
    AdaptiveQualifiedModelEndpointPool,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    OpenAICompatibleModelEndpoint,
    AsyncioJsonTransport,
)


def build_openai_compatible_qualified_endpoint(
    binding: QualifiedModelEndpointBinding,
    *,
    api_key: str = "",
    timeout_s: float | None = None,
    task_group: TaskGroupPort,
    admission_registry: ModelAdmissionRegistryPort,
    observers: tuple[object, ...] = (),
) -> ModelEndpointPort:
    """Materialize one endpoint from a platform-qualified binding."""

    headers: tuple[tuple[str, str], ...] = ()
    if api_key:
        headers = (("Authorization", f"Bearer {api_key}"),)
    admission = admission_registry.controller_for(
        deployment_id=binding.deployment_id,
        deployment_generation=binding.deployment_generation,
        qualified_capacity=binding.max_admitted_concurrency,
    )
    return OpenAICompatibleModelEndpoint(
        route=ModelEndpointRoute(
            deployment_id=binding.deployment_id,
            deployment_generation=binding.deployment_generation,
            base_url=binding.base_url,
            completion_path=binding.completion_path,
            timeout_s=binding.timeout_s if timeout_s is None else timeout_s,
        ),
        transport=AsyncioJsonTransport(headers=headers),
        task_group=task_group,
        admission=admission,
        observers=observers,
    )


__all__ = [
    "build_adaptive_operational_endpoint_pool",
    "build_adaptive_qualified_endpoint_pool",
    "build_openai_compatible_qualified_endpoint",
]


def build_adaptive_operational_endpoint_pool(
    replica_set: OperationalModelEndpointReplicaSet,
    *,
    api_key: str = "",
    task_group: TaskGroupPort,
    admission_registry: ModelAdmissionRegistryPort,
    observers: tuple[object, ...] = (),
    selection_policy: ModelEndpointReplicaSelectionPolicyPort | None = None,
) -> AdaptiveOperationalModelEndpointPool:
    """Bind exact live routes without asserting qualification equivalence."""

    headers: tuple[tuple[str, str], ...] = ()
    if api_key:
        headers = (("Authorization", f"Bearer {api_key}"),)

    def factory(replica) -> ModelEndpointPort:
        admission = admission_registry.controller_for(
            deployment_id=replica.deployment_id,
            deployment_generation=replica.deployment_generation,
            qualified_capacity=replica.capacity,
        )
        return OpenAICompatibleModelEndpoint(
            route=replica.route,
            transport=AsyncioJsonTransport(headers=headers),
            task_group=task_group,
            admission=admission,
            observers=observers,
        )

    return AdaptiveOperationalModelEndpointPool(
        replica_set, factory, selection_policy=selection_policy
    )



def build_adaptive_qualified_endpoint_pool(
    replica_set: QualifiedModelEndpointReplicaSet,
    *,
    api_key: str = "",
    timeout_s: float | None = None,
    task_group: TaskGroupPort,
    admission_registry: ModelAdmissionRegistryPort,
    observers: tuple[object, ...] = (),
    selection_policy: ModelEndpointReplicaSelectionPolicyPort | None = None,
) -> AdaptiveQualifiedModelEndpointPool:
    """Bind all qualified replicas to one adaptive operational dispatcher."""

    def factory(binding: QualifiedModelEndpointBinding) -> ModelEndpointPort:
        return build_openai_compatible_qualified_endpoint(
            binding,
            api_key=api_key,
            timeout_s=timeout_s,
            task_group=task_group,
            admission_registry=admission_registry,
            observers=observers,
        )

    return AdaptiveQualifiedModelEndpointPool(
        replica_set, factory, selection_policy=selection_policy
    )
