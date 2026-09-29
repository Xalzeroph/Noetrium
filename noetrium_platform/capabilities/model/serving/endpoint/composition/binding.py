from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.capabilities.model.serving.api.deployment import FrozenDeploymentSet
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointFactoryPort,
    ModelEndpointPort,
    ModelEndpointRoute,
)


@dataclass(frozen=True, slots=True)
class FrozenEndpointBinding:
    """A model endpoint bound to one exact deployment generation."""

    deployment_id: str
    deployment_generation: str
    endpoint: ModelEndpointPort


class FrozenDeploymentEndpointBinder:
    """Resolve a role only through the frozen deployment set and route table."""

    def __init__(
        self,
        *,
        routes: tuple[ModelEndpointRoute, ...],
        endpoint_factory: ModelEndpointFactoryPort,
    ) -> None:
        ids = [route.deployment_id for route in routes]
        if len(ids) != len(set(ids)):
            raise ValueError("endpoint routes cannot duplicate deployment identities")
        self._routes = {route.deployment_id: route for route in routes}
        self._endpoint_factory = endpoint_factory

    def bind(
        self,
        deployments: FrozenDeploymentSet,
        *,
        role: str,
        capability_id: str,
        input_schema_id: str,
        output_schema_id: str,
    ) -> FrozenEndpointBinding:
        key=(role,capability_id,input_schema_id,output_schema_id)
        if any(type(value) is not str or not value.strip() for value in key):
            raise ValueError("endpoint binding requires exact role/capability protocol")
        assignments = [item for item in deployments.assignments if item.protocol_key == key]
        if len(assignments) != 1:
            raise ValueError(f"model capability must have exactly one frozen deployment assignment: {key}")
        deployment_id = assignments[0].deployment_id
        deployment = next(
            (item for item in deployments.deployments if item.deployment_id == deployment_id),
            None,
        )
        if deployment is None:
            raise ValueError(f"frozen deployment assignment is missing deployment: {deployment_id}")
        route = self._routes.get(deployment_id)
        if route is None:
            raise ValueError(f"no endpoint route for frozen deployment: {deployment_id}")
        if route.deployment_generation != deployment.deployment_digest:
            raise ValueError(f"endpoint route generation drift for deployment: {deployment_id}")
        return FrozenEndpointBinding(
            deployment_id=deployment_id,
            deployment_generation=deployment.deployment_digest,
            endpoint=self._endpoint_factory.create(route),
        )


__all__ = ["FrozenDeploymentEndpointBinder", "FrozenEndpointBinding"]
