from __future__ import annotations

from typing import Callable

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentCatalogPort,
    ModelDeploymentRuntimePort,
    ModelDeploymentSpec,
    ModelDeploymentStatus,
    ModelDesiredState,
    ModelRuntimeState,
)


class ModelFleetRuntime:
    """Batch desired-state convergence for a deployment fleet.

    Per-deployment lifecycle stays in ModelDeploymentRuntime.  This authority is
    intentionally limited to iteration, isolation of per-deployment failures,
    and fleet-level desired-state convergence.
    """

    def __init__(
        self,
        catalog: ModelDeploymentCatalogPort,
        runtime: ModelDeploymentRuntimePort,
    ) -> None:
        self._catalog = catalog
        self._runtime = runtime

    def status_all(self) -> tuple[ModelDeploymentStatus, ...]:
        return tuple(self._run_fleet_action(spec, self._runtime.status) for spec in self._catalog.deployments())

    def reconcile(self) -> tuple[ModelDeploymentStatus, ...]:
        values: list[ModelDeploymentStatus] = []
        for spec in self._catalog.deployments():
            try:
                current = self._runtime.status(spec.deployment_id)
                if spec.desired_state is ModelDesiredState.RUNNING and current.runtime_state is not ModelRuntimeState.RUNNING:
                    values.append(self._runtime.start(spec.deployment_id))
                elif spec.desired_state is ModelDesiredState.STOPPED and current.runtime_state in {
                    ModelRuntimeState.RUNNING,
                    ModelRuntimeState.UPDATE_PENDING,
                }:
                    values.append(self._runtime.stop(spec.deployment_id))
                else:
                    values.append(current)
            except Exception as exc:
                values.append(self._management_failure_status(spec, exc))
        return tuple(values)

    def start_all(self) -> tuple[ModelDeploymentStatus, ...]:
        return tuple(self._run_fleet_action(spec, self._runtime.start) for spec in self._catalog.deployments())

    def stop_all(self) -> tuple[ModelDeploymentStatus, ...]:
        return tuple(self._run_fleet_action(spec, self._runtime.stop) for spec in self._catalog.deployments())

    @staticmethod
    def _management_failure_status(spec: ModelDeploymentSpec, exc: Exception) -> ModelDeploymentStatus:
        runtime_state = ModelRuntimeState.MISSING if isinstance(exc, (FileNotFoundError, KeyError)) else ModelRuntimeState.ERROR
        return ModelDeploymentStatus(
            spec.deployment_id,
            spec.service_id,
            spec.desired_state,
            runtime_state,
            detail=type(exc).__name__,
        )

    @classmethod
    def _run_fleet_action(
        cls, spec: ModelDeploymentSpec, action: Callable[[str], ModelDeploymentStatus]
    ) -> ModelDeploymentStatus:
        try:
            return action(spec.deployment_id)
        except Exception as exc:
            return cls._management_failure_status(spec, exc)


__all__ = ["ModelFleetRuntime"]
