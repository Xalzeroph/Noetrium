from __future__ import annotations

from threading import RLock

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentCatalogPort,
    ModelDeploymentGeneration,
    ModelDeploymentSpec,
    ModelDeploymentStatus,
    ModelDesiredState,
    ModelRuntimeState,
    ModelServiceRuntimeFactoryPort,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.substrate.api import ServiceContractDrift

from .applied import AppliedModelDeployment
from .launch_materializer import ModelLaunchMaterializer
from .applied_store import AppliedModelDeploymentStore


class ModelDeploymentRuntime:
    """Service lifecycle authority for exact desired/applied model generations.

    Read operations may resolve by logical deployment id. Every mutation carries
    a generation snapshot joining the desired spec and the exact applied service
    contract, so a delayed owner can never retarget itself onto a replacement
    process generation merely because the deployment id was reused.
    """

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
        self._lock = RLock()

    @staticmethod
    def _generation_value(
        desired: ModelDeploymentSpec,
        applied: AppliedModelDeployment | None,
    ) -> ModelDeploymentGeneration:
        return ModelDeploymentGeneration(
            desired.deployment_id,
            canonical_digest(desired),
            None if applied is None else applied.contract.digest(),
        )

    def _snapshot_unlocked(
        self,
        deployment_id: str,
    ) -> tuple[ModelDeploymentGeneration, ModelDeploymentSpec, AppliedModelDeployment | None]:
        desired = self._catalog.deployment(deployment_id)
        applied = self._applied_store.read(deployment_id)
        return self._generation_value(desired, applied), desired, applied

    def generation(self, deployment_id: str) -> ModelDeploymentGeneration:
        with self._lock:
            generation, _desired, _applied = self._snapshot_unlocked(deployment_id)
            return generation

    def _require_generation(
        self,
        expected: ModelDeploymentGeneration,
    ) -> tuple[ModelDeploymentSpec, AppliedModelDeployment | None]:
        if type(expected) is not ModelDeploymentGeneration:
            raise TypeError(
                "model deployment mutation requires ModelDeploymentGeneration"
            )
        current, desired, applied = self._snapshot_unlocked(expected.deployment_id)
        if current != expected:
            raise RuntimeError(
                "stale model deployment generation: "
                f"{expected.deployment_id}"
            )
        return desired, applied

    def _stop_applied(
        self,
        desired: ModelDeploymentSpec,
        applied: AppliedModelDeployment | None,
    ) -> ModelDeploymentStatus:
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
            # The runtime-wide mutation lock and the exact contract snapshot make
            # this clear a CAS over the currently applied generation.
            current = self._applied_store.read(desired.deployment_id)
            if (
                current is None
                or current.contract.digest() != applied.contract.digest()
            ):
                raise RuntimeError(
                    "model applied generation changed during physical stop: "
                    f"{desired.deployment_id}"
                )
            self._applied_store.clear(desired.deployment_id)
        return ModelDeploymentStatus(
            desired.deployment_id,
            desired.service_id,
            desired.desired_state,
            ModelRuntimeState.STOPPED if outcome.stopped else ModelRuntimeState.ERROR,
        )

    def start(
        self,
        generation: ModelDeploymentGeneration,
    ) -> ModelDeploymentStatus:
        with self._lock:
            desired_before, applied = self._require_generation(generation)
            spec = self._catalog.set_desired_state(
                desired_before.deployment_id,
                ModelDesiredState.RUNNING,
            )
            desired_contract, desired_environment = self._materializer.materialize(spec)

            if applied is not None:
                runtime = self._service_factory.open(
                    applied.contract,
                    environment=applied.environment,
                    readiness_url=applied.spec.readiness_url,
                )
                observation = runtime.reconcile_exact(applied.contract)
                if (
                    observation.process is not None
                    and applied.contract.digest() == desired_contract.digest()
                ):
                    return ModelDeploymentStatus(
                        spec.deployment_id,
                        spec.service_id,
                        spec.desired_state,
                        ModelRuntimeState.RUNNING,
                        observation.process.pid,
                        "already-running",
                    )
                if observation.process is not None:
                    stopped = runtime.stop_exact(applied.contract)
                    if not stopped.stopped:
                        raise RuntimeError(
                            "existing model process did not stop before deployment replacement: "
                            f"{spec.deployment_id}"
                        )
                current = self._applied_store.read(spec.deployment_id)
                if (
                    current is None
                    or current.contract.digest() != applied.contract.digest()
                ):
                    raise RuntimeError(
                        "model applied generation changed during replacement: "
                        f"{spec.deployment_id}"
                    )
                self._applied_store.clear(spec.deployment_id)

            runtime = self._service_factory.open(
                desired_contract,
                environment=desired_environment,
                readiness_url=spec.readiness_url,
            )
            outcome = runtime.start_exact(desired_contract)
            self._applied_store.put(
                AppliedModelDeployment(spec, desired_contract, desired_environment)
            )
            return ModelDeploymentStatus(
                spec.deployment_id,
                spec.service_id,
                spec.desired_state,
                ModelRuntimeState.RUNNING,
                outcome.process.pid,
                outcome.ready_evidence_ref,
            )

    def stop(
        self,
        generation: ModelDeploymentGeneration,
    ) -> ModelDeploymentStatus:
        with self._lock:
            desired_before, applied = self._require_generation(generation)
            desired = self._catalog.set_desired_state(
                desired_before.deployment_id,
                ModelDesiredState.STOPPED,
            )
            return self._stop_applied(desired, applied)

    def shutdown(
        self,
        generation: ModelDeploymentGeneration,
    ) -> ModelDeploymentStatus:
        """Stop one exact physical generation without changing desired state."""

        with self._lock:
            desired, applied = self._require_generation(generation)
            return self._stop_applied(desired, applied)

    def restart(
        self,
        generation: ModelDeploymentGeneration,
    ) -> ModelDeploymentStatus:
        with self._lock:
            stopped = self.stop(generation)
            if stopped.runtime_state is not ModelRuntimeState.STOPPED:
                raise RuntimeError(
                    "model deployment restart refused because the prior physical "
                    f"generation did not stop: {generation.deployment_id}"
                )
            return self.start(self.generation(generation.deployment_id))

    def status(self, deployment_id: str) -> ModelDeploymentStatus:
        with self._lock:
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

    def remove_deployment(
        self,
        generation: ModelDeploymentGeneration,
    ) -> bool:
        with self._lock:
            try:
                desired, applied = self._require_generation(generation)
            except KeyError:
                # Ambiguous caller failure after a successful durable removal is
                # retry-safe only while both desired and applied identities are
                # absent. A newly recreated deployment would resolve above and
                # fail the generation CAS instead.
                if self._applied_store.read(generation.deployment_id) is None:
                    return True
                raise

            stopped = self._stop_applied(desired, applied)
            if stopped.runtime_state is not ModelRuntimeState.STOPPED:
                raise RuntimeError(
                    "model deployment removal refused because the physical "
                    f"generation did not stop: {generation.deployment_id}"
                )

            current_desired = self._catalog.deployment(generation.deployment_id)
            if canonical_digest(current_desired) != generation.desired_spec_digest:
                raise RuntimeError(
                    "model desired generation changed during physical removal: "
                    f"{generation.deployment_id}"
                )
            return self._catalog.remove(generation.deployment_id)


__all__ = ["ModelDeploymentRuntime"]
