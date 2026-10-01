from __future__ import annotations

from threading import RLock

from noetrium_platform.capabilities.model.deployment.api import (
    ModelAppliedRuntimeIdentity,
    ModelDeploymentCatalogPort,
    ModelDeploymentGeneration,
    ModelDeploymentSpec,
    ModelDeploymentStatus,
    ModelDesiredState,
    ModelRuntimeState,
    ModelServiceRuntimeFactoryPort,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.capabilities.model.serving.runtime.process_identity import ProcessIdentity
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
            None if applied is None else applied.runtime_digest,
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

    def _stop_cleared_orphans_unlocked(
        self,
        desired: ModelDeploymentSpec,
    ) -> int:
        """Stop exact physical processes fenced by terminal applied tombstones.

        A cleared snapshot is higher-order evidence that its process generation
        must never be live again. If the exact process still exists after a crash
        window, stop it using the frozen historical contract instead of
        reconstructing any launch-time dynamic parameters from current host state.
        """

        stopped = 0
        for cleared in self._applied_store.cleared_snapshots(
            desired.deployment_id
        ):
            runtime = self._service_factory.open(
                cleared.spec,
                cleared.contract,
                environment=cleared.environment,
                readiness_url=cleared.spec.readiness_url,
            )
            observation = runtime.reconcile_exact(cleared.contract)
            if observation.process is None:
                continue
            if observation.process != cleared.process:
                raise RuntimeError(
                    "cleared model process generation drifted before orphan stop: "
                    f"{desired.deployment_id}"
                )
            outcome = runtime.stop_exact(
                cleared.contract,
                cleared.process,
            )
            if not outcome.stopped:
                raise RuntimeError(
                    "cleared model physical process did not stop: "
                    f"{desired.deployment_id}"
                )
            stopped += 1
        return stopped

    def _stop_applied(
        self,
        desired: ModelDeploymentSpec,
        applied: AppliedModelDeployment | None,
    ) -> ModelDeploymentStatus:
        if applied is None:
            orphan_count = self._stop_cleared_orphans_unlocked(desired)
            return ModelDeploymentStatus(
                desired.deployment_id,
                desired.service_id,
                desired.desired_state,
                ModelRuntimeState.STOPPED,
                detail=(
                    "cleared-orphan-stopped"
                    if orphan_count
                    else "not-applied"
                ),
            )
        runtime = self._service_factory.open(
            applied.spec,
            applied.contract,
            environment=applied.environment,
            readiness_url=applied.spec.readiness_url,
        )
        observation = runtime.reconcile_exact(applied.contract)
        if (
            observation.process is not None
            and observation.process != applied.process
        ):
            raise RuntimeError(
                "model applied process generation drifted before physical stop: "
                f"{desired.deployment_id}"
            )
        outcome = (
            runtime.stop_exact(applied.contract, applied.process)
            if observation.process is not None
            else None
        )
        stopped_converged = outcome is None or outcome.stopped
        if stopped_converged:
            # The runtime-wide mutation lock plus the exact persisted process
            # identity make this clear a CAS over one physical lifetime.
            current = self._applied_store.read(desired.deployment_id)
            if (
                current is None
                or current.runtime_digest != applied.runtime_digest
            ):
                raise RuntimeError(
                    "model applied generation changed during physical stop: "
                    f"{desired.deployment_id}"
                )
            self._applied_store.clear(
                desired.deployment_id,
                expected_runtime_digest=applied.runtime_digest,
            )
        return ModelDeploymentStatus(
            desired.deployment_id,
            desired.service_id,
            desired.desired_state,
            ModelRuntimeState.STOPPED if stopped_converged else ModelRuntimeState.ERROR,
        )

    def recover_applied(
        self,
        generation: ModelDeploymentGeneration,
    ) -> ModelDeploymentGeneration:
        """Rebuild a lost applied proof from one exact live service only.

        This recovery path is deliberately non-creative: it reconciles the
        durable service state against the freshly materialized exact contract
        and refuses recovery if the physical process is absent or drifted.
        It never starts a replacement process.
        """
        with self._lock:
            desired, applied = self._require_generation(generation)
            if applied is not None:
                return self._generation_value(desired, applied)
            if self._applied_store.cleared_snapshots(desired.deployment_id):
                raise RuntimeError(
                    "cleared applied model generation cannot be recovered; "
                    "retire the stale realization and re-place it: "
                    f"{desired.deployment_id}"
                )

            self._materializer.validate_materialization_inputs(desired)
            contract, environment = self._materializer.materialize(desired)
            runtime = self._service_factory.open(
                desired,
                contract,
                environment=environment,
                readiness_url=desired.readiness_url,
            )
            observation = runtime.reconcile_exact(contract)
            if observation.process is None:
                raise RuntimeError(
                    "model durable physical process is missing during applied "
                    f"recovery: {desired.deployment_id}"
                )

            recovered = AppliedModelDeployment(
                desired,
                contract,
                environment,
                observation.process,
            )
            self._applied_store.put(recovered)
            persisted = self._applied_store.read(desired.deployment_id)
            if (
                persisted is None
                or persisted.runtime_digest != recovered.runtime_digest
            ):
                raise RuntimeError(
                    "model applied recovery did not durably converge: "
                    f"{desired.deployment_id}"
                )
            return self._generation_value(desired, persisted)

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

            if applied is not None:
                self._materializer.validate_materialization_inputs(spec)
                same_materialization = (
                    canonical_digest(spec) == canonical_digest(applied.spec)
                    and self._materializer.matches_applied(spec, applied.contract)
                )
                runtime = self._service_factory.open(
                    applied.spec,
                    applied.contract,
                    environment=applied.environment,
                    readiness_url=applied.spec.readiness_url,
                )
                observation = runtime.reconcile_exact(applied.contract)
                if (
                    observation.process is not None
                    and observation.process != applied.process
                ):
                    raise RuntimeError(
                        "model applied process generation drifted before replacement: "
                        f"{spec.deployment_id}"
                    )
                if observation.process == applied.process and same_materialization:
                    return ModelDeploymentStatus(
                        spec.deployment_id,
                        spec.service_id,
                        spec.desired_state,
                        ModelRuntimeState.RUNNING,
                        observation.process.pid,
                        "already-running",
                    )
                if observation.process is not None:
                    stopped = runtime.stop_exact(applied.contract, applied.process)
                    if not stopped.stopped:
                        raise RuntimeError(
                            "existing model process did not stop before deployment replacement: "
                            f"{spec.deployment_id}"
                        )
                current = self._applied_store.read(spec.deployment_id)
                if (
                    current is None
                    or current.runtime_digest != applied.runtime_digest
                ):
                    raise RuntimeError(
                        "model applied generation changed during replacement: "
                        f"{spec.deployment_id}"
                    )
                self._applied_store.clear(
                    spec.deployment_id,
                    expected_runtime_digest=applied.runtime_digest,
                )

            desired_contract, desired_environment = self._materializer.materialize(spec)
            runtime = self._service_factory.open(
                spec,
                desired_contract,
                environment=desired_environment,
                readiness_url=spec.readiness_url,
            )
            outcome = runtime.start_exact(desired_contract)
            self._applied_store.put(
                AppliedModelDeployment(
                    spec,
                    desired_contract,
                    desired_environment,
                    outcome.process,
                )
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
                applied.spec,
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
            if observation.process != applied.process:
                return ModelDeploymentStatus(
                    desired.deployment_id,
                    desired.service_id,
                    desired.desired_state,
                    ModelRuntimeState.DRIFTED,
                    observation.process.pid,
                    "applied-process-generation-drift",
                )
            try:
                self._materializer.validate_materialization_inputs(desired)
                pending = (
                    canonical_digest(desired) != canonical_digest(applied.spec)
                    or not self._materializer.matches_applied(
                        desired,
                        applied.contract,
                    )
                )
            except (FileNotFoundError, KeyError) as exc:
                return ModelDeploymentStatus(
                    desired.deployment_id,
                    desired.service_id,
                    desired.desired_state,
                    ModelRuntimeState.UPDATE_PENDING,
                    observation.process.pid,
                    f"desired-resource-missing:{type(exc).__name__}",
                )
            return ModelDeploymentStatus(
                desired.deployment_id,
                desired.service_id,
                desired.desired_state,
                ModelRuntimeState.UPDATE_PENDING if pending else ModelRuntimeState.RUNNING,
                observation.process.pid,
                "desired-config-pending" if pending else "",
            )

    def applied_identity(
        self,
        deployment_id: str,
    ) -> ModelAppliedRuntimeIdentity:
        """Return exact immutable process/launch identity for qualification."""
        with self._lock:
            generation, desired, applied = self._snapshot_unlocked(deployment_id)
            if applied is None or generation.applied_runtime_digest is None:
                raise RuntimeError(
                    f"model deployment has no applied runtime: {deployment_id}"
                )
            runtime = self._service_factory.open(
                applied.spec,
                applied.contract,
                environment=applied.environment,
                readiness_url=applied.spec.readiness_url,
            )
            observation = runtime.reconcile_exact(applied.contract)
            if observation.process is None:
                raise RuntimeError(
                    f"model applied process is not running: {deployment_id}"
                )
            if observation.process != applied.process:
                raise RuntimeError(
                    "model applied process generation drifted during identity read: "
                    f"{deployment_id}"
                )
            process_identity = ProcessIdentity.from_argv(
                applied.process.pid,
                applied.process.start_identity,
                applied.contract.argv,
            )
            return ModelAppliedRuntimeIdentity(
                deployment_id=deployment_id,
                desired_spec_digest=generation.desired_spec_digest,
                applied_runtime_digest=generation.applied_runtime_digest,
                service_contract_digest=applied.contract.digest(),
                pid=process_identity.pid,
                process_start_marker=process_identity.start_marker,
                argv_digest=process_identity.argv_digest,
            )

    def remove_deployment(
        self,
        generation: ModelDeploymentGeneration,
    ) -> bool:
        with self._lock:
            if type(generation) is not ModelDeploymentGeneration:
                raise TypeError(
                    "model deployment mutation requires ModelDeploymentGeneration"
                )
            try:
                current, desired, applied = self._snapshot_unlocked(
                    generation.deployment_id
                )
            except (KeyError, FileNotFoundError):
                # Removal publishes a durable retirement tombstone before the
                # desired record disappears, so absence is an idempotent terminal
                # state and the logical id cannot later be recycled. Exact
                # process-clear tombstones are no longer needed once that
                # permanent identity retirement has committed.
                if self._applied_store.read(generation.deployment_id) is None:
                    self._applied_store.purge_cleared_after_retirement(
                        generation.deployment_id
                    )
                    return True
                raise

            if current.desired_spec_digest != generation.desired_spec_digest:
                raise RuntimeError(
                    "stale model deployment generation: "
                    f"{generation.deployment_id}"
                )
            if applied is not None:
                if (
                    generation.applied_runtime_digest is None
                    or current.applied_runtime_digest
                    != generation.applied_runtime_digest
                ):
                    raise RuntimeError(
                        "stale model deployment generation: "
                        f"{generation.deployment_id}"
                    )
                stopped = self._stop_applied(desired, applied)
                if stopped.runtime_state is not ModelRuntimeState.STOPPED:
                    raise RuntimeError(
                        "model deployment removal refused because the physical "
                        f"generation did not stop: {generation.deployment_id}"
                    )
            elif generation.applied_runtime_digest is None:
                # No live applied pointer exists. A crash window may still have
                # left the exact process named by a terminal clear tombstone
                # running; converge that orphan before retiring logical identity.
                stopped = self._stop_applied(desired, None)
                if stopped.runtime_state is not ModelRuntimeState.STOPPED:
                    raise RuntimeError(
                        "model deployment orphan cleanup did not converge: "
                        f"{generation.deployment_id}"
                    )
            else:
                # Retry after the exact captured physical generation was already
                # proven stopped and its applied record was cleared. Desired
                # identity must still match; terminal retirement prevents later
                # deployment-id reuse from becoming a false continuation.
                pass

            current_desired = self._catalog.deployment(generation.deployment_id)
            if canonical_digest(current_desired) != generation.desired_spec_digest:
                raise RuntimeError(
                    "model desired generation changed during physical removal: "
                    f"{generation.deployment_id}"
                )
            retired = self._catalog.remove(generation.deployment_id)
            if retired:
                self._applied_store.purge_cleared_after_retirement(
                    generation.deployment_id
                )
            return retired


__all__ = ["ModelDeploymentRuntime"]
