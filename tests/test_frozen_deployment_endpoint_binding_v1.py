from __future__ import annotations

import pytest

from noetrium_platform.capabilities.model.serving.api import FrozenDeploymentIdentity, FrozenDeploymentSet, FrozenRoleAssignment
from noetrium_platform.capabilities.model.serving.endpoint.api import ModelEndpointRoute
from noetrium_platform.capabilities.model.serving.endpoint.composition import FrozenDeploymentEndpointBinder


class Factory:
    def __init__(self) -> None:
        self.routes = []

    def create(self, route: ModelEndpointRoute):
        self.routes.append(route)
        return f"endpoint:{route.deployment_id}"


def _deployments(*, role: str = "planner", deployment_id: str = "dep-1") -> FrozenDeploymentSet:
    digest = "d" * 64
    return FrozenDeploymentSet(
        role_manifest_digest="r" * 64,
        assignments=(FrozenRoleAssignment(role, deployment_id),),
        deployments=(FrozenDeploymentIdentity(
            deployment_id=deployment_id,
            deployment_digest=digest,
            stack_digest="s" * 64,
            artifact_digest="a" * 64,
            runtime_identity_digest="t" * 64,
            qualification_certificate_digest="q" * 64,
            host_identity_digest="h" * 64,
            gpu_uuids=("gpu-1",),
        ),),
    )


def test_binder_resolves_role_from_frozen_deployment_and_preserves_digest() -> None:
    factory = Factory()
    binder = FrozenDeploymentEndpointBinder(
        routes=(ModelEndpointRoute("dep-1", "d" * 64, "http://127.0.0.1:30000"),),
        endpoint_factory=factory,
    )

    result = binder.bind(_deployments(), role="planner")

    assert result.deployment_id == "dep-1"
    assert result.deployment_generation == "d" * 64
    assert result.endpoint == "endpoint:dep-1"
    assert len(factory.routes) == 1


def test_binder_rejects_route_generation_drift_before_endpoint_factory() -> None:
    factory = Factory()
    binder = FrozenDeploymentEndpointBinder(
        routes=(ModelEndpointRoute("dep-1", "e" * 64, "http://127.0.0.1:30000"),),
        endpoint_factory=factory,
    )
    with pytest.raises(ValueError, match="generation drift"):
        binder.bind(_deployments(), role="planner")
    assert factory.routes == []


def test_binder_rejects_unassigned_role_without_fallback() -> None:
    binder = FrozenDeploymentEndpointBinder(
        routes=(ModelEndpointRoute("dep-1", "d" * 64, "http://127.0.0.1:30000"),),
        endpoint_factory=Factory(),
    )
    with pytest.raises(ValueError, match="exactly one"):
        binder.bind(_deployments(), role="semantic")

