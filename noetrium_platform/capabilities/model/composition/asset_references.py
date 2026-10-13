from __future__ import annotations

from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentCatalogPort, ModelDesiredState


class DeploymentModelAssetReferences:
    """Parent-level adapter: deployment facts projected into the narrow asset-reference query port."""

    def __init__(self, deployments: ModelDeploymentCatalogPort) -> None:
        self._deployments = deployments

    def references(self, model_id: str) -> tuple[str, ...]:
        return tuple(
            sorted(spec.deployment_id for spec in self._deployments.deployments() if spec.model_id == model_id)
        )

    def active_references(self, model_id: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                spec.deployment_id
                for spec in self._deployments.deployments()
                if spec.model_id == model_id and spec.desired_state is ModelDesiredState.RUNNING
            )
        )


__all__ = ["DeploymentModelAssetReferences"]
