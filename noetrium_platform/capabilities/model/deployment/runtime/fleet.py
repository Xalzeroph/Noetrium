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
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception

from .auto_recovery import DurableModelAutoRecoveryAuthority


class ModelFleetRuntime:
    """Batch desired-state convergence with durable bounded auto-recovery.

    Manual start/restart is separate from automatic reconciliation. Automatic
    starts are authorized by a crash-durable circuit so controller or host
    restarts cannot erase repeated-failure history and create restart storms.
    """

    def __init__(
        self,
        catalog: ModelDeploymentCatalogPort,
        runtime: ModelDeploymentRuntimePort,
        auto_recovery: DurableModelAutoRecoveryAuthority,
    ) -> None:
        self._catalog = catalog
        self._runtime = runtime
        self._auto_recovery = auto_recovery

    def status_all(self) -> tuple[ModelDeploymentStatus, ...]:
        return tuple(
            self._run_status_action(spec)
            for spec in self._catalog.deployments()
        )

    @staticmethod
    def _status_detail(
        current: ModelDeploymentStatus,
        detail: str,
    ) -> ModelDeploymentStatus:
        resolved = detail if not current.detail else f"{current.detail};{detail}"
        return ModelDeploymentStatus(
            current.deployment_id,
            current.service_id,
            current.desired_state,
            current.runtime_state,
            current.pid,
            resolved,
        )

    def _reconcile_running(
        self,
        spec: ModelDeploymentSpec,
        generation: ModelDeploymentGeneration,
        current: ModelDeploymentStatus,
    ) -> ModelDeploymentStatus:
        if current.runtime_state is ModelRuntimeState.RUNNING:
            self._auto_recovery.record_running(
                spec.deployment_id,
                generation.desired_spec_digest,
            )
            return current

        if current.runtime_state is ModelRuntimeState.DRIFTED:
            return self._status_detail(
                current,
                "auto-recovery-blocked:generation-drift",
            )
        if current.runtime_state is ModelRuntimeState.MISSING:
            return self._status_detail(
                current,
                "auto-recovery-blocked:runtime-missing",
            )

        decision = self._auto_recovery.claim_attempt(
            spec.deployment_id,
            generation.desired_spec_digest,
        )
        if not decision.allow:
            detail = decision.reason
            if decision.retry_after_seconds is not None:
                detail = (
                    f"{detail}:retry-after="
                    f"{max(0.0, decision.retry_after_seconds):.3f}s"
                )
            return self._status_detail(current, detail)

        claim_id = decision.claim_id
        if claim_id is None:
            raise RuntimeError("authorized model auto-recovery is missing claim identity")
        try:
            started = self._runtime.start(generation)
        except Exception as exc:
            descriptor = describe_exception(exc)
            state = self._auto_recovery.record_failure(
                spec.deployment_id,
                generation.desired_spec_digest,
                claim_id,
                descriptor.error_digest,
            )
            detail = (
                f"auto-recovery-failed:{descriptor.error_type}:"
                f"{descriptor.safe_message}:"
                f"{descriptor.error_digest[:16]}"
            )
            if state.circuit_open:
                detail += ":circuit-open"
            return ModelDeploymentStatus(
                spec.deployment_id,
                spec.service_id,
                spec.desired_state,
                (
                    ModelRuntimeState.MISSING
                    if isinstance(exc, (FileNotFoundError, KeyError))
                    else ModelRuntimeState.ERROR
                ),
                detail=detail,
            )

        if started.runtime_state is ModelRuntimeState.RUNNING:
            self._auto_recovery.record_attempt_success(
                spec.deployment_id,
                generation.desired_spec_digest,
                claim_id,
            )
        return started

    def reconcile(self) -> tuple[ModelDeploymentStatus, ...]:
        values: list[ModelDeploymentStatus] = []
        for spec in self._catalog.deployments():
            try:
                generation = self._runtime.generation(spec.deployment_id)
                current = self._runtime.status(spec.deployment_id)
                if spec.desired_state is ModelDesiredState.RUNNING:
                    values.append(
                        self._reconcile_running(spec, generation, current)
                    )
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

    def reset_auto_recovery(self, deployment_id: str) -> bool:
        generation = self._runtime.generation(deployment_id)
        self._auto_recovery.reset(
            deployment_id,
            generation.desired_spec_digest,
        )
        return True

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
    def _management_failure_status(
        spec: ModelDeploymentSpec,
        exc: Exception,
    ) -> ModelDeploymentStatus:
        runtime_state = (
            ModelRuntimeState.MISSING
            if isinstance(exc, (FileNotFoundError, KeyError))
            else ModelRuntimeState.ERROR
        )
        descriptor = describe_exception(exc)
        return ModelDeploymentStatus(
            spec.deployment_id,
            spec.service_id,
            spec.desired_state,
            runtime_state,
            detail=(
                f"{descriptor.error_type}:"
                f"{descriptor.error_digest[:16]}"
            ),
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
