from __future__ import annotations

from typing import Callable

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentCatalogPort,
    ModelDeploymentGeneration,
    ModelDeploymentRuntimePort,
    ModelDeploymentSelector,
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
        return tuple(
            self._run_status_action(spec)
            for spec in self._catalog.deployments()
        )

    def reconcile(self) -> tuple[ModelDeploymentStatus, ...]:
        values: list[ModelDeploymentStatus] = []
        for spec in self._catalog.deployments():
            try:
                generation = self._runtime.generation(spec.deployment_id)
                current = self._runtime.status(spec.deployment_id)
                if (
                    spec.desired_state is ModelDesiredState.RUNNING
                    and current.runtime_state is not ModelRuntimeState.RUNNING
                ):
                    values.append(self._runtime.start(generation))
                elif (
                    spec.desired_state is ModelDesiredState.STOPPED
                    and current.runtime_state
                    in {
                        ModelRuntimeState.RUNNING,
                        ModelRuntimeState.UPDATE_PENDING,
                    }
                ):
                    values.append(self._runtime.stop(generation))
                else:
                    values.append(current)
            except Exception as exc:
                values.append(self._management_failure_status(spec, exc))
        return tuple(values)

    def start_all(self) -> tuple[ModelDeploymentStatus, ...]:
        return tuple(
            self._run_mutation_action(spec, self._runtime.start)
            for spec in self._catalog.deployments()
        )

    def stop_all(self) -> tuple[ModelDeploymentStatus, ...]:
        return tuple(
            self._run_mutation_action(spec, self._runtime.stop)
            for spec in self._catalog.deployments()
        )

    def shutdown_all(self) -> tuple[ModelDeploymentStatus, ...]:
        """Stop physical model processes while preserving desired deployment state."""

        return tuple(
            self._run_mutation_action(spec, self._runtime.shutdown)
            for spec in self._catalog.deployments()
        )

    def remove_selected(
        self,
        selector: ModelDeploymentSelector,
    ) -> tuple[str, ...]:
        """Physically stop and remove one selected deployment ownership class.

        This is intentionally fail-closed rather than status-projecting: callers
        use it as a resource-lifecycle fence, so any deployment that cannot be
        proven removed must prevent lower resource layers from being released.
        Repeated calls converge because already-removed deployments no longer
        appear in the catalog selection.
        """

        if type(selector) is not ModelDeploymentSelector:
            raise TypeError("model fleet removal requires ModelDeploymentSelector")
        removed: list[str] = []
        errors: list[BaseException] = []
        for spec in reversed(self._catalog.select(selector)):
            try:
                generation = self._runtime.generation(spec.deployment_id)
                self._runtime.remove_deployment(generation)
            except BaseException as exc:
                errors.append(exc)
            else:
                removed.append(spec.deployment_id)
        if errors:
            raise ExceptionGroup(
                "selected model deployment removal failed",
                errors,
            )
        return tuple(sorted(removed))

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

    def _run_status_action(
        self,
        spec: ModelDeploymentSpec,
    ) -> ModelDeploymentStatus:
        try:
            return self._runtime.status(spec.deployment_id)
        except Exception as exc:
            return self._management_failure_status(spec, exc)

    def _run_mutation_action(
        self,
        spec: ModelDeploymentSpec,
        action: Callable[[ModelDeploymentGeneration], ModelDeploymentStatus],
    ) -> ModelDeploymentStatus:
        try:
            return action(self._runtime.generation(spec.deployment_id))
        except Exception as exc:
            return self._management_failure_status(spec, exc)


__all__ = ["ModelFleetRuntime"]
