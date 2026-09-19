from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.execution.operation.api import (
    EffectReconciliationOutcome,
    EffectReconciliationVerdict,
)
from noetrium_platform.research.experimentation.run.api.artifacts import (
    RunArtifactVerificationPort,
)
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.run.manifest.api import RunLaunchManifest
from noetrium_platform.research.experimentation.run.manifest.api.evidence import (
    EvidenceBundleReceipt,
)
from noetrium_platform.research.experimentation.run.runtime import (
    RunMachineSession,
    RunPhase,
)

from ..api.contracts import (
    RunControlAction,
    RunControlActionFailure,
    RunControlCheckpointStorePort,
    RunControlConflict,
    RunControlEvidencePort,
    RunControlIntegrityError,
    RunControlLifecyclePort,
    RunControlNotFound,
    RunControlPhase,
    RunControlPreparedOperation,
    RunControlReceipt,
    RunControlReconciliationPort,
    RunControlRequest,
    RunControlStaleRevision,
    RunControlTransitionOutcome,
    RunEvidenceValidity,
    RunExecutionOutcome,
    RunOutcomeProjection,
    RunScientificValidity,
    RunTaskOutcome,
)


_EXECUTION_OUTCOME_BY_PHASE = {
    RunControlPhase.CREATED: RunExecutionOutcome.NOT_STARTED,
    RunControlPhase.RUNNING: RunExecutionOutcome.IN_PROGRESS,
    RunControlPhase.STOPPED: RunExecutionOutcome.STOPPED,
    RunControlPhase.RECOVERY_REQUIRED: RunExecutionOutcome.RECOVERY_REQUIRED,
    RunControlPhase.COMPLETED: RunExecutionOutcome.SUCCEEDED,
    RunControlPhase.FAILED: RunExecutionOutcome.FAILED,
    RunControlPhase.CLOSED: RunExecutionOutcome.CLOSED,
}


class DurableRunControl:
    """External lifecycle/evidence coordinator over authoritative RunMachine state."""

    def __init__(
        self,
        *,
        identity: RunIdentity,
        manifest: RunLaunchManifest,
        run_machine: RunMachineSession,
        lifecycle: RunControlLifecyclePort,
        checkpoint_store: RunControlCheckpointStorePort,
        reconciliation: RunControlReconciliationPort,
        evidence: RunControlEvidencePort,
        artifact_verifier: RunArtifactVerificationPort,
    ) -> None:
        if type(identity) is not RunIdentity:
            raise TypeError("run control identity must be RunIdentity")
        if type(manifest) is not RunLaunchManifest:
            raise TypeError("run control manifest must be RunLaunchManifest")
        if not isinstance(run_machine, RunMachineSession):
            raise TypeError("run control requires RunMachineSession")
        if run_machine.identity != identity:
            raise ValueError("run control RunMachine identity mismatch")
        if (
            run_machine.binding.experiment_spec_digest
            != manifest.experiment_spec_digest
        ):
            raise ValueError("run control RunMachine experiment identity mismatch")
        self.identity = identity
        self.manifest = manifest
        self.run_identity_digest = identity.digest()
        self.run_manifest_digest = manifest.digest()
        self._machine = run_machine
        self._lifecycle = lifecycle
        self._checkpoint_store = checkpoint_store
        self._reconciliation = reconciliation
        self._evidence = evidence
        self._artifact_verifier = artifact_verifier
        self._machine.bind_manifest(self.run_manifest_digest)

    @property
    def machine(self) -> RunMachineSession:
        return self._machine

    def _require_target(self, request: RunControlRequest) -> None:
        target = request.target
        if target.run_id != self.identity.run_id:
            raise RunControlConflict(
                "run control target belongs to a different run"
            )
        if target.run_manifest_digest != self.run_manifest_digest:
            raise RunControlConflict(
                "run control target manifest digest drifted"
            )

    def _require_revision(
        self,
        request: RunControlRequest,
        *,
        allow_matching_pending: bool = False,
        operation_id: str | None = None,
    ) -> None:
        expected = request.target.expected_revision
        if expected is None:
            return
        actual = self._machine.control_revision
        if expected == actual:
            return
        if allow_matching_pending and operation_id is not None:
            pending = self._machine.pending_control_operation
            if (
                pending is not None
                and pending.get("operation_id") == operation_id
                and pending.get("base_revision") == expected
            ):
                return
        raise RunControlStaleRevision(
            f"run control expected revision {expected}, current revision {actual}"
        )

    def _pending(self) -> RunControlPreparedOperation | None:
        value = self._machine.pending_control_operation
        if value is None:
            return None
        try:
            action = RunControlAction(value["action"])
            base_phase = RunControlPhase(value["base_phase"])
            return RunControlPreparedOperation(
                operation_id=value["operation_id"],
                action=action,
                base_revision=value["base_revision"],
                base_phase=base_phase,
                base_latest_checkpoint_id=value.get(
                    "base_latest_checkpoint_id"
                ),
                base_checkpoint_manifest_digest=value.get(
                    "base_checkpoint_manifest_digest"
                ),
                restore_checkpoint_id=value.get("restore_checkpoint_id"),
                restore_checkpoint_manifest_digest=value.get(
                    "restore_checkpoint_manifest_digest"
                ),
                restore_cycle_identity_digest=value.get(
                    "restore_cycle_identity_digest"
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RunControlIntegrityError(
                "RunMachine pending control operation is malformed"
            ) from exc

    def _phase(self) -> RunControlPhase:
        return RunControlPhase(self._machine.phase.value)

    def _receipt(
        self,
        request: RunControlRequest,
        *,
        evidence_receipt: EvidenceBundleReceipt | None = None,
    ) -> RunControlReceipt:
        cut = self._machine.cut
        if cut is None:
            raise RunControlNotFound("RunMachine has no accepted journal head")
        phase = self._phase()
        return RunControlReceipt(
            action=request.action,
            run_id=self.identity.run_id,
            run_identity_digest=self.run_identity_digest,
            run_manifest_digest=self.run_manifest_digest,
            phase=phase,
            machine_cut=cut,
            latest_checkpoint_id=self._machine.latest_checkpoint_id,
            checkpoint_manifest_digest=(
                self._machine.latest_checkpoint_manifest_digest
            ),
            pending_operation=self._pending(),
            evidence_bundle_receipt=evidence_receipt,
            outcomes=RunOutcomeProjection(
                _EXECUTION_OUTCOME_BY_PHASE[phase],
                RunTaskOutcome.NOT_EVALUATED,
                (
                    RunEvidenceValidity.FINALIZED_VALID
                    if evidence_receipt is not None
                    else RunEvidenceValidity.NOT_FINALIZED
                    if request.action is RunControlAction.EVIDENCE
                    else RunEvidenceValidity.NOT_OBSERVED
                ),
                RunScientificValidity.NOT_EVALUATED,
            ),
        )

    @staticmethod
    def _require_outcome(
        outcome: RunControlTransitionOutcome,
        *,
        allowed: frozenset[RunControlPhase],
        action: RunControlAction,
    ) -> RunControlPhase:
        if (
            type(outcome) is not RunControlTransitionOutcome
            or outcome.phase not in allowed
        ):
            raise RunControlIntegrityError(
                f"run control lifecycle returned invalid {action.value} outcome"
            )
        return outcome.phase

    def _operation_id(
        self,
        request: RunControlRequest,
        *,
        checkpoint_manifest_digest: str | None = None,
    ) -> str:
        cycle = request.restore_cycle_identity
        return canonical_digest({
            "schema_version": "run-control.machine.v1",
            "run_id": self.identity.run_id,
            "run_identity_digest": self.run_identity_digest,
            "run_manifest_digest": self.run_manifest_digest,
            "action": request.action.value,
            "base_revision": request.target.expected_revision,
            "restore_checkpoint_id": request.restore_checkpoint_id,
            "restore_checkpoint_manifest_digest": checkpoint_manifest_digest,
            "restore_cycle_identity_digest": (
                None if cycle is None else cycle.digest()
            ),
        })

    def _inspect(self, request: RunControlRequest) -> RunControlReceipt:
        self._require_revision(request)
        return self._receipt(request)

    def _load_restore_checkpoint(
        self,
        checkpoint_id: str,
        cycle: DecisionCycleIdentity,
    ):
        from noetrium_platform.research.experimentation.checkpoint.api.contracts import (
            RunCheckpointManifest,
        )

        try:
            bundle = self._checkpoint_store.load(checkpoint_id)
        except BaseException as exc:
            raise RunControlIntegrityError(
                "run control restore checkpoint cannot be loaded"
            ) from exc
        checkpoint = bundle.manifest
        if type(checkpoint) is not RunCheckpointManifest:
            raise RunControlIntegrityError(
                "run control checkpoint store returned invalid manifest type"
            )
        if checkpoint.checkpoint_id != checkpoint_id:
            raise RunControlIntegrityError(
                "run control checkpoint id does not match request"
            )
        if (
            checkpoint.run_id != self.identity.run_id
            or checkpoint.session_id != self.identity.session_id
        ):
            raise RunControlIntegrityError(
                "run control checkpoint belongs to another run/session"
            )
        if (
            checkpoint.experiment_spec_digest
            != self.manifest.experiment_spec_digest
        ):
            raise RunControlIntegrityError(
                "run control checkpoint experiment identity drifted"
            )
        expected_cycle_identity = (
            self.identity.run_id,
            self.identity.session_id,
            self.identity.trace_id,
            checkpoint.decision_cycle_id,
        )
        actual_cycle_identity = (
            cycle.run_id,
            cycle.session_id,
            cycle.trace_id,
            cycle.decision_cycle_id,
        )
        if actual_cycle_identity != expected_cycle_identity:
            raise RunControlIntegrityError(
                "run control restore cycle belongs to another run/checkpoint"
            )
        if checkpoint.cycle_identity_digest != cycle.digest():
            raise RunControlIntegrityError(
                "run control restore cycle digest does not match checkpoint"
            )
        return checkpoint

    def _prepare(
        self,
        request: RunControlRequest,
        *,
        checkpoint_manifest_digest: str | None = None,
    ) -> tuple[RunControlPreparedOperation, bool]:
        expected = request.target.expected_revision
        if expected is None:
            raise RunControlIntegrityError(
                "effectful run control requires expected revision"
            )
        operation_id = self._operation_id(
            request,
            checkpoint_manifest_digest=checkpoint_manifest_digest,
        )
        self._require_revision(
            request,
            allow_matching_pending=True,
            operation_id=operation_id,
        )
        pending_before = self._pending()
        if pending_before is not None:
            if pending_before.operation_id != operation_id:
                raise RunControlConflict(
                    "another run control operation is already pending"
                )
            return pending_before, False

        cycle = request.restore_cycle_identity
        created = self._machine.prepare_control(
            operation_id=operation_id,
            action=request.action.value,
            restore_checkpoint_id=request.restore_checkpoint_id,
            restore_checkpoint_manifest_digest=checkpoint_manifest_digest,
            restore_cycle_identity_digest=(
                None if cycle is None else cycle.digest()
            ),
        )
        pending = self._pending()
        if pending is None or pending.operation_id != operation_id:
            raise RunControlIntegrityError(
                "RunMachine did not publish prepared control authority"
            )
        return pending, created

    def _resolve(
        self,
        prepared: RunControlPreparedOperation,
        phase: RunControlPhase,
        *,
        checkpoint_id: str | None,
        checkpoint_manifest_digest: str | None,
        failure_digest: str | None = None,
    ) -> None:
        self._machine.resolve_control(
            operation_id=prepared.operation_id,
            phase=RunPhase(phase.value),
            checkpoint_id=checkpoint_id,
            checkpoint_manifest_digest=checkpoint_manifest_digest,
            failure_digest=failure_digest,
        )

    def _leave_uncertain(
        self,
        request: RunControlRequest,
        prepared: RunControlPreparedOperation,
    ) -> RunControlReceipt:
        pending = self._pending()
        if pending is None or pending.operation_id != prepared.operation_id:
            raise RunControlIntegrityError(
                "uncertain run control effect lost its prepared authority"
            )
        if self._machine.phase is not RunPhase.RECOVERY_REQUIRED:
            raise RunControlIntegrityError(
                "uncertain run control effect must remain recovery_required"
            )
        return self._receipt(request)

    def _effectful_run(self, request: RunControlRequest) -> RunControlReceipt:
        if (
            self._machine.phase is RunPhase.RUNNING
            and self._pending() is None
        ):
            self._require_revision(request)
            return self._receipt(request)
        prepared, created = self._prepare(request)
        if not created:
            return self._receipt(request)
        try:
            phase = self._require_outcome(
                self._lifecycle.run(
                    self.identity,
                    self.manifest,
                    operation_id=prepared.operation_id,
                ),
                allowed=frozenset({
                    RunControlPhase.RUNNING,
                    RunControlPhase.RECOVERY_REQUIRED,
                    RunControlPhase.FAILED,
                }),
                action=RunControlAction.RUN,
            )
        except BaseException as exc:
            raise RunControlActionFailure(
                self._leave_uncertain(request, prepared)
            ) from exc
        if phase is RunControlPhase.RECOVERY_REQUIRED:
            return self._leave_uncertain(request, prepared)
        self._resolve(
            prepared,
            phase,
            checkpoint_id=prepared.base_latest_checkpoint_id,
            checkpoint_manifest_digest=(
                prepared.base_checkpoint_manifest_digest
            ),
        )
        return self._receipt(request)

    def _effectful_stop(self, request: RunControlRequest) -> RunControlReceipt:
        if (
            self._pending() is None
            and self._machine.phase
            in {RunPhase.STOPPED, RunPhase.COMPLETED}
        ):
            self._require_revision(request)
            return self._receipt(request)
        if self._machine.phase is not RunPhase.RUNNING:
            raise RunControlConflict(
                f"run control cannot stop from {self._machine.phase.value}"
            )
        prepared, created = self._prepare(request)
        if not created:
            return self._receipt(request)
        try:
            phase = self._require_outcome(
                self._lifecycle.stop(
                    self.identity,
                    self.manifest,
                    operation_id=prepared.operation_id,
                ),
                allowed=frozenset({
                    RunControlPhase.STOPPED,
                    RunControlPhase.COMPLETED,
                    RunControlPhase.RECOVERY_REQUIRED,
                    RunControlPhase.FAILED,
                }),
                action=RunControlAction.STOP,
            )
        except BaseException as exc:
            raise RunControlActionFailure(
                self._leave_uncertain(request, prepared)
            ) from exc
        if phase is RunControlPhase.RECOVERY_REQUIRED:
            return self._leave_uncertain(request, prepared)
        self._resolve(
            prepared,
            phase,
            checkpoint_id=prepared.base_latest_checkpoint_id,
            checkpoint_manifest_digest=(
                prepared.base_checkpoint_manifest_digest
            ),
        )
        return self._receipt(request)

    def _effectful_resume(
        self,
        request: RunControlRequest,
    ) -> RunControlReceipt:
        checkpoint_id = request.restore_checkpoint_id
        cycle = request.restore_cycle_identity
        if checkpoint_id is None or cycle is None:
            raise RunControlIntegrityError(
                "resume requires checkpoint and restore cycle"
            )
        checkpoint = self._load_restore_checkpoint(checkpoint_id, cycle)
        checkpoint_digest = checkpoint.digest()
        if (
            self._pending() is None
            and self._machine.phase is RunPhase.RUNNING
            and self._machine.latest_checkpoint_id == checkpoint.checkpoint_id
            and self._machine.latest_checkpoint_manifest_digest
            == checkpoint_digest
        ):
            self._require_revision(request)
            return self._receipt(request)
        if self._machine.phase not in {
            RunPhase.STOPPED,
            RunPhase.RECOVERY_REQUIRED,
        }:
            raise RunControlConflict(
                f"run control cannot resume from {self._machine.phase.value}"
            )
        prepared, created = self._prepare(
            request,
            checkpoint_manifest_digest=checkpoint_digest,
        )
        if not created:
            return self._receipt(request)
        try:
            phase = self._require_outcome(
                self._lifecycle.resume(
                    self.identity,
                    self.manifest,
                    checkpoint,
                    cycle,
                    operation_id=prepared.operation_id,
                ),
                allowed=frozenset({
                    RunControlPhase.RUNNING,
                    RunControlPhase.RECOVERY_REQUIRED,
                    RunControlPhase.FAILED,
                }),
                action=RunControlAction.RESUME,
            )
        except BaseException as exc:
            raise RunControlActionFailure(
                self._leave_uncertain(request, prepared)
            ) from exc
        if phase is RunControlPhase.RECOVERY_REQUIRED:
            return self._leave_uncertain(request, prepared)
        self._resolve(
            prepared,
            phase,
            checkpoint_id=checkpoint.checkpoint_id,
            checkpoint_manifest_digest=checkpoint_digest,
        )
        return self._receipt(request)

    def _resolved_reconciliation_phase(
        self,
        pending: RunControlPreparedOperation,
        verdict: EffectReconciliationVerdict,
    ) -> RunControlPhase | None:
        if type(verdict) is not EffectReconciliationVerdict:
            raise RunControlIntegrityError(
                "run control reconciliation provider returned invalid verdict"
            )
        if verdict.request_id != pending.operation_id:
            raise RunControlIntegrityError(
                "run control reconciliation request_id drifted"
            )
        if (
            verdict.outcome is EffectReconciliationOutcome.UNKNOWN
            or verdict.verification_required
        ):
            return None
        if verdict.request_digest != pending.operation_id:
            raise RunControlIntegrityError(
                "run control reconciliation request digest drifted"
            )
        if verdict.outcome is EffectReconciliationOutcome.EXECUTED:
            return {
                RunControlAction.RUN: RunControlPhase.RUNNING,
                RunControlAction.STOP: RunControlPhase.STOPPED,
                RunControlAction.RESUME: RunControlPhase.RUNNING,
            }[pending.action]
        if verdict.outcome is EffectReconciliationOutcome.NOT_EXECUTED:
            if pending.action is RunControlAction.RUN:
                return RunControlPhase.FAILED
            return pending.base_phase
        if verdict.outcome is EffectReconciliationOutcome.REJECTED:
            if pending.action is RunControlAction.RUN:
                return RunControlPhase.FAILED
            return pending.base_phase
        raise RunControlIntegrityError(
            "run control reconciliation verdict is unsupported"
        )

    def _reconcile(self, request: RunControlRequest) -> RunControlReceipt:
        self._require_revision(request)
        pending = self._pending()
        if pending is None:
            if self._machine.phase is RunPhase.RUNNING:
                return self._receipt(request)
            raise RunControlConflict(
                "run control has no unresolved prepared operation"
            )
        proof = self._reconciliation.reconcile(
            self.identity,
            self.manifest,
            pending,
        )
        phase = self._resolved_reconciliation_phase(pending, proof)
        if phase is None:
            return self._receipt(request)

        checkpoint_id = pending.base_latest_checkpoint_id
        checkpoint_digest = pending.base_checkpoint_manifest_digest
        if (
            pending.action is RunControlAction.RESUME
            and phase is RunControlPhase.RUNNING
        ):
            checkpoint_id = pending.restore_checkpoint_id
            checkpoint_digest = (
                pending.restore_checkpoint_manifest_digest
            )
        self._resolve(
            pending,
            phase,
            checkpoint_id=checkpoint_id,
            checkpoint_manifest_digest=checkpoint_digest,
        )
        return self._receipt(request)

    def _evidence_receipt(
        self,
        request: RunControlRequest,
    ) -> RunControlReceipt:
        self._require_revision(request)
        receipt = self._evidence.evidence(self.identity, self.manifest)
        if receipt is not None:
            if type(receipt) is not EvidenceBundleReceipt:
                raise RunControlIntegrityError(
                    "run control evidence provider returned invalid receipt"
                )
            if (
                receipt.run_id != self.identity.run_id
                or receipt.run_manifest_digest != self.run_manifest_digest
            ):
                raise RunControlIntegrityError(
                    "run control evidence belongs to another run/manifest"
                )
            try:
                self._artifact_verifier.verify_finalized(
                    receipt.manifest_artifact_receipt
                )
            except BaseException as exc:
                raise RunControlIntegrityError(
                    "run control evidence manifest is not finalized authority"
                ) from exc
        return self._receipt(
            request,
            evidence_receipt=receipt,
        )

    def execute(self, request: RunControlRequest) -> RunControlReceipt:
        if type(request) is not RunControlRequest:
            raise TypeError(
                "run control execute requires RunControlRequest"
            )
        self._require_target(request)
        if request.action is RunControlAction.INSPECT:
            return self._inspect(request)
        if request.action is RunControlAction.RUN:
            return self._effectful_run(request)
        if request.action is RunControlAction.STOP:
            return self._effectful_stop(request)
        if request.action is RunControlAction.RESUME:
            return self._effectful_resume(request)
        if request.action is RunControlAction.RECONCILE:
            return self._reconcile(request)
        if request.action is RunControlAction.EVIDENCE:
            return self._evidence_receipt(request)
        raise RunControlIntegrityError(
            "run control action is unsupported"
        )


__all__ = ["DurableRunControl"]
