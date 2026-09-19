from __future__ import annotations

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentCatalogPort,
    ModelDeploymentStatus,
    ModelDesiredState,
    ModelRuntimeState,
    ModelServiceRuntimeFactoryPort,
)
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceContractDrift

from .applied import AppliedModelDeployment
from .launch_materializer import ModelLaunchMaterializer
from .applied_store import AppliedModelDeploymentStore


class ModelDeploymentRuntime:
    """Service lifecycle authority for desired/applied model deployments."""

    def __init__(
        self,
        applied_store: AppliedModelDeploymentStore,
        catalog: ModelDeploymentCatalogPort,
        materializer: ModelLaunchMaterializer,
        service_factory: ModelServiceRuntimeFactoryPort,
    ) -> None:
        self._applied_store = applied_store
        self._catalog = catalog
        self._materializer = materializer
        self._service_factory = service_factory

    def start(self, deployment_id: str) -> ModelDeploymentStatus:
        spec = self._catalog.set_desired_state(deployment_id, ModelDesiredState.RUNNING)
        desired_contract, desired_environment = self._materializer.materialize(spec)
        applied = self._applied_store.read(deployment_id)
        if applied is not None:
            runtime = self._service_factory.open(
                applied.contract,
                environment=applied.environment,
                readiness_url=applied.spec.readiness_url,
            )
            observation = runtime.reconcile_exact(applied.contract)
            if observation.process is not None and applied.contract.digest() == desired_contract.digest():
                return ModelDeploymentStatus(
                    spec.deployment_id,
                    spec.service_id,
                    spec.desired_state,
                    ModelRuntimeState.RUNNING,
                    observation.process.pid,
                    "already-running",
                )
            if observation.process is not None:
                runtime.stop_exact(applied.contract)
            self._applied_store.clear(deployment_id)
        runtime = self._service_factory.open(
            desired_contract,
            environment=desired_environment,
            readiness_url=spec.readiness_url,
        )
        outcome = runtime.start_exact(desired_contract)
        self._applied_store.put(AppliedModelDeployment(spec, desired_contract, desired_environment))
        return ModelDeploymentStatus(
            spec.deployment_id,
            spec.service_id,
            spec.desired_state,
            ModelRuntimeState.RUNNING,
            outcome.process.pid,
            outcome.ready_evidence_ref,
        )

    def stop(self, deployment_id: str) -> ModelDeploymentStatus:
        desired = self._catalog.set_desired_state(deployment_id, ModelDesiredState.STOPPED)
        applied = self._applied_store.read(deployment_id)
        if applied is None:
            return ModelDeploymentStatus(
                desired.deployment_id,
                desired.service_id,
                desired.desired_state,
                ModelRuntimeState.STOPPED,
                detail="not-applied",
            )
        runtime = self._service_factory.open(
            applied.contract,
            environment=applied.environment,
            readiness_url=applied.spec.readiness_url,
        )
        outcome = runtime.stop_exact(applied.contract)
        if outcome.stopped:
            self._applied_store.clear(deployment_id)
        return ModelDeploymentStatus(
            desired.deployment_id,
            desired.service_id,
            desired.desired_state,
            ModelRuntimeState.STOPPED if outcome.stopped else ModelRuntimeState.ERROR,
        )

    def restart(self, deployment_id: str) -> ModelDeploymentStatus:
        self.stop(deployment_id)
        return self.start(deployment_id)

    def status(self, deployment_id: str) -> ModelDeploymentStatus:
        desired = self._catalog.deployment(deployment_id)
        applied = self._applied_store.read(deployment_id)
        if applied is None:
            return ModelDeploymentStatus(
                desired.deployment_id,
                desired.service_id,
                desired.desired_state,
                ModelRuntimeState.STOPPED,
                detail="not-applied",
            )
        runtime = self._service_factory.open(
            applied.contract,
            environment=applied.environment,
            readiness_url=applied.spec.readiness_url,
        )
        try:
            observation = runtime.reconcile_exact(applied.contract)
        except ServiceContractDrift as exc:
            return ModelDeploymentStatus(
                desired.deployment_id,
                desired.service_id,
                desired.desired_state,
                ModelRuntimeState.DRIFTED,
                detail=type(exc).__name__,
            )
        if observation.process is None:
            return ModelDeploymentStatus(
                desired.deployment_id,
                desired.service_id,
                desired.desired_state,
                ModelRuntimeState.STOPPED,
                detail="applied-process-missing",
            )
        try:
            desired_contract, _ = self._materializer.materialize(desired)
        except (FileNotFoundError, KeyError) as exc:
            return ModelDeploymentStatus(
                desired.deployment_id,
                desired.service_id,
                desired.desired_state,
                ModelRuntimeState.UPDATE_PENDING,
                observation.process.pid,
                f"desired-resource-missing:{type(exc).__name__}",
            )
        pending = applied.contract.digest() != desired_contract.digest()
        return ModelDeploymentStatus(
            desired.deployment_id,
            desired.service_id,
            desired.desired_state,
            ModelRuntimeState.UPDATE_PENDING if pending else ModelRuntimeState.RUNNING,
            observation.process.pid,
            "desired-config-pending" if pending else "",
        )

    def remove_deployment(self, deployment_id: str) -> bool:
        if self._applied_store.read(deployment_id) is not None:
            self.stop(deployment_id)
        return self._catalog.remove(deployment_id)


__all__ = ["ModelDeploymentRuntime"]
