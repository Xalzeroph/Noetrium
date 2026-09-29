from __future__ import annotations

from dataclasses import replace

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentSelector,
    ModelDeploymentSpec,
    ModelDesiredState,
)
from noetrium_platform.capabilities.model.asset.api import ModelAssetDeploymentAdmissionPort
from .deployment_registry import ModelDeploymentRegistry


class ModelDeploymentCatalog:
    """Mutable desired deployment configuration authority."""

    def __init__(
        self,
        asset_registry: ModelAssetDeploymentAdmissionPort,
        deployment_registry: ModelDeploymentRegistry,
    ) -> None:
        self._asset_registry = asset_registry
        self._deployment_registry = deployment_registry

    def put_deployment(self, spec: ModelDeploymentSpec) -> ModelDeploymentSpec:
        normalized = replace(
            spec,
            tags=tuple(sorted({tag.strip() for tag in spec.tags if tag.strip()})),
        )
        # Hold the model asset's cross-process retirement fence until the
        # desired deployment is durably published. This closes the window in
        # which asset validation could succeed, retirement could publish, GC
        # could see no deployment yet, and the stale deployment could commit
        # after physical bytes were removed.
        with self._asset_registry.deployment_admission(spec.model_id):
            return self._deployment_registry.put(normalized)

    def deployment(self, deployment_id: str) -> ModelDeploymentSpec:
        return self._deployment_registry.get(deployment_id)

    def deployments(self) -> tuple[ModelDeploymentSpec, ...]:
        return self._deployment_registry.all()

    def select(self, selector: ModelDeploymentSelector = ModelDeploymentSelector()) -> tuple[ModelDeploymentSpec, ...]:
        required_tags = set(selector.tags)
        values = []
        for spec in self.deployments():
            if required_tags and not required_tags.issubset(spec.tags):
                continue
            if selector.model_id is not None and spec.model_id != selector.model_id:
                continue
            if selector.engine is not None and spec.engine != selector.engine:
                continue
            values.append(spec)
        return tuple(values)

    def set_desired_state_selected(
        self, selector: ModelDeploymentSelector, state: ModelDesiredState
    ) -> tuple[ModelDeploymentSpec, ...]:
        return tuple(self.set_desired_state(spec.deployment_id, state) for spec in self.select(selector))

    def set_desired_state(self, deployment_id: str, state: ModelDesiredState) -> ModelDeploymentSpec:
        return self._deployment_registry.put(replace(self.deployment(deployment_id), desired_state=state))

    def set_gpu_devices(self, deployment_id: str, gpu_devices: tuple[str, ...]) -> ModelDeploymentSpec:
        normalized = tuple(dict.fromkeys(str(device).strip() for device in gpu_devices if str(device).strip()))
        return self.put_deployment(
            replace(
                self.deployment(deployment_id),
                gpu_devices=normalized,
                gpu_memory_reservation_bytes=(),
            )
        )

    def remove(self, deployment_id: str) -> bool:
        return self._deployment_registry.remove(deployment_id)


__all__ = ["ModelDeploymentCatalog"]
