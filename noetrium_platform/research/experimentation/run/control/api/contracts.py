from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from noetrium_platform.foundation.kernel.kernel import MachineCut, canonical_digest
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.run.manifest.api import RunLaunchManifest
from noetrium_platform.research.experimentation.run.manifest.api.evidence import EvidenceBundleReceipt
from noetrium_platform.research.execution.operation.api import EffectReconciliationVerdict

if TYPE_CHECKING:
    from noetrium_platform.research.experimentation.checkpoint.api.contracts import RunCheckpointManifest


_HEX = frozenset("0123456789abcdef")


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _digest(value: object, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(ch not in _HEX for ch in text):
        raise ValueError(f"{field} must be canonical lowercase SHA-256")
    return text


def _optional_text(value: object, field: str) -> str | None:
    return None if value is None else _text(value, field)


def _optional_digest(value: object, field: str) -> str | None:
    return None if value is None else _digest(value, field)


class RunControlAction(StrEnum):
    RUN = "run"
    INSPECT = "inspect"
    STOP = "stop"
    RESUME = "resume"
    RECONCILE = "reconcile"
    EVIDENCE = "evidence"


class RunControlPhase(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"
    RECOVERY_REQUIRED = "recovery_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class RunControlTarget:
    run_id: str
    run_manifest_digest: str
    expected_revision: int | None = None

    def __post_init__(self) -> None:
        _text(self.run_id, "run control target run_id")
        _digest(self.run_manifest_digest, "run control target run_manifest_digest")
        if self.expected_revision is not None and (
            type(self.expected_revision) is not int or self.expected_revision < 1
        ):
            raise ValueError(
                "run control target expected_revision must be a positive integer or None"
            )


@dataclass(frozen=True, slots=True)
class RunControlRequest:
    action: RunControlAction
    target: RunControlTarget
    restore_checkpoint_id: str | None = None
    restore_cycle_identity: DecisionCycleIdentity | None = None

    def __post_init__(self) -> None:
        if type(self.action) is not RunControlAction:
            raise TypeError("run control action must be RunControlAction")
        if type(self.target) is not RunControlTarget:
            raise TypeError("run control target must be RunControlTarget")
        _optional_text(
            self.restore_checkpoint_id,
            "run control restore_checkpoint_id",
        )
        if self.restore_cycle_identity is not None and type(
            self.restore_cycle_identity
        ) is not DecisionCycleIdentity:
            raise TypeError(
                "run control restore_cycle_identity must be DecisionCycleIdentity or None"
            )
        if self.action in {
            RunControlAction.RUN,
            RunControlAction.STOP,
            RunControlAction.RESUME,
            RunControlAction.RECONCILE,
        } and self.target.expected_revision is None:
            raise ValueError(
                "state-changing run control action requires expected_revision"
            )
        if self.action is RunControlAction.RESUME:
            if (
                self.restore_checkpoint_id is None
                or self.restore_cycle_identity is None
            ):
                raise ValueError(
                    "run control resume requires checkpoint and restore cycle identity"
                )
        elif (
            self.restore_checkpoint_id is not None
            or self.restore_cycle_identity is not None
        ):
            raise ValueError(
                "run control restore fields are valid only for resume"
            )


@dataclass(frozen=True, slots=True)
class RunControlPreparedOperation:
    """Typed projection of RunMachine.pending_control_operation."""

    operation_id: str
    action: RunControlAction
    base_revision: int
    base_phase: RunControlPhase
    base_latest_checkpoint_id: str | None
    base_checkpoint_manifest_digest: str | None
    restore_checkpoint_id: str | None = None
    restore_checkpoint_manifest_digest: str | None = None
    restore_cycle_identity_digest: str | None = None

    def __post_init__(self) -> None:
        _digest(self.operation_id, "run control operation_id")
        if type(self.action) is not RunControlAction:
            raise TypeError("run control prepared action must be RunControlAction")
        if type(self.base_revision) is not int or self.base_revision < 1:
            raise ValueError("run control prepared base_revision must be positive")
        if type(self.base_phase) is not RunControlPhase:
            raise TypeError("run control prepared base_phase must be RunControlPhase")
        base_checkpoint = _optional_text(
            self.base_latest_checkpoint_id,
            "run control base checkpoint id",
        )
        base_manifest = _optional_digest(
            self.base_checkpoint_manifest_digest,
            "run control base checkpoint manifest digest",
        )
        restore_checkpoint = _optional_text(
            self.restore_checkpoint_id,
            "run control restore checkpoint id",
        )
        restore_manifest = _optional_digest(
            self.restore_checkpoint_manifest_digest,
            "run control restore checkpoint manifest digest",
        )
        restore_cycle = _optional_digest(
            self.restore_cycle_identity_digest,
            "run control restore cycle identity digest",
        )
        if self.action is RunControlAction.RESUME:
            if (
                restore_checkpoint is None
                or restore_manifest is None
                or restore_cycle is None
            ):
                raise ValueError(
                    "run control resume preparation requires exact restore identity"
                )
        elif any(
            value is not None
            for value in (restore_checkpoint, restore_manifest, restore_cycle)
        ):
            raise ValueError(
                "run control restore identity is valid only for resume"
            )

    @property
    def digest(self) -> str:
        return canonical_digest({
            "operation_id": self.operation_id,
            "action": self.action.value,
            "base_revision": self.base_revision,
            "base_phase": self.base_phase.value,
            "base_latest_checkpoint_id": self.base_latest_checkpoint_id,
            "base_checkpoint_manifest_digest": self.base_checkpoint_manifest_digest,
            "restore_checkpoint_id": self.restore_checkpoint_id,
            "restore_checkpoint_manifest_digest": self.restore_checkpoint_manifest_digest,
            "restore_cycle_identity_digest": self.restore_cycle_identity_digest,
        })


class RunExecutionOutcome(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    STOPPED = "stopped"
    RECOVERY_REQUIRED = "recovery_required"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CLOSED = "closed"


class RunTaskOutcome(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class RunEvidenceValidity(StrEnum):
    NOT_OBSERVED = "not_observed"
    NOT_FINALIZED = "not_finalized"
    FINALIZED_VALID = "finalized_valid"


class RunScientificValidity(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class RunOutcomeProjection:
    execution: RunExecutionOutcome
    task: RunTaskOutcome
    evidence: RunEvidenceValidity
    scientific: RunScientificValidity

    def __post_init__(self) -> None:
        if tuple(
            type(value)
            for value in (
                self.execution,
                self.task,
                self.evidence,
                self.scientific,
            )
        ) != (
            RunExecutionOutcome,
            RunTaskOutcome,
            RunEvidenceValidity,
            RunScientificValidity,
        ):
            raise TypeError("run outcome projection fields require exact enum types")


_EXECUTION_BY_PHASE = {
    RunControlPhase.CREATED: RunExecutionOutcome.NOT_STARTED,
    RunControlPhase.RUNNING: RunExecutionOutcome.IN_PROGRESS,
    RunControlPhase.STOPPED: RunExecutionOutcome.STOPPED,
    RunControlPhase.RECOVERY_REQUIRED: RunExecutionOutcome.RECOVERY_REQUIRED,
    RunControlPhase.COMPLETED: RunExecutionOutcome.SUCCEEDED,
    RunControlPhase.FAILED: RunExecutionOutcome.FAILED,
    RunControlPhase.CLOSED: RunExecutionOutcome.CLOSED,
}


@dataclass(frozen=True, slots=True)
class RunControlReceipt:
    action: RunControlAction
    run_id: str
    run_identity_digest: str
    run_manifest_digest: str
    phase: RunControlPhase
    machine_cut: MachineCut
    latest_checkpoint_id: str | None
    checkpoint_manifest_digest: str | None
    pending_operation: RunControlPreparedOperation | None
    evidence_bundle_receipt: EvidenceBundleReceipt | None
    outcomes: RunOutcomeProjection

    def __post_init__(self) -> None:
        if type(self.action) is not RunControlAction:
            raise TypeError("run control receipt action must be RunControlAction")
        _text(self.run_id, "run control receipt run_id")
        _digest(self.run_identity_digest, "run control receipt run_identity_digest")
        _digest(self.run_manifest_digest, "run control receipt run_manifest_digest")
        if type(self.phase) is not RunControlPhase:
            raise TypeError("run control receipt phase must be RunControlPhase")
        if not isinstance(self.machine_cut, MachineCut):
            raise TypeError("run control receipt requires MachineCut")
        if self.machine_cut.machine_id != f"research-run:{self.run_id}":
            raise ValueError("run control receipt MachineCut belongs to another run")
        checkpoint_id = _optional_text(
            self.latest_checkpoint_id,
            "run control latest_checkpoint_id",
        )
        checkpoint_digest = _optional_digest(
            self.checkpoint_manifest_digest,
            "run control checkpoint_manifest_digest",
        )
        if self.pending_operation is not None and not isinstance(
            self.pending_operation,
            RunControlPreparedOperation,
        ):
            raise TypeError(
                "run control pending_operation must be RunControlPreparedOperation or None"
            )
        if self.evidence_bundle_receipt is not None and type(
            self.evidence_bundle_receipt
        ) is not EvidenceBundleReceipt:
            raise TypeError(
                "run control evidence_bundle_receipt must be EvidenceBundleReceipt or None"
            )
        if type(self.outcomes) is not RunOutcomeProjection:
            raise TypeError("run control outcomes must be RunOutcomeProjection")
        if self.outcomes.execution is not _EXECUTION_BY_PHASE[self.phase]:
            raise ValueError(
                "run control execution outcome contradicts RunMachine phase"
            )
        expected_evidence = (
            RunEvidenceValidity.FINALIZED_VALID
            if self.evidence_bundle_receipt is not None
            else RunEvidenceValidity.NOT_FINALIZED
            if self.action is RunControlAction.EVIDENCE
            else RunEvidenceValidity.NOT_OBSERVED
        )
        if self.outcomes.evidence is not expected_evidence:
            raise ValueError(
                "run control evidence validity contradicts finalized evidence authority"
            )
        if self.outcomes.task is not RunTaskOutcome.NOT_EVALUATED:
            raise ValueError("run control cannot claim task outcome authority")
        if self.outcomes.scientific is not RunScientificValidity.NOT_EVALUATED:
            raise ValueError("run control cannot claim scientific validity authority")

    @property
    def control_revision(self) -> int:
        return self.machine_cut.revision

    @property
    def receipt_digest(self) -> str:
        return canonical_digest({
            "action": self.action.value,
            "run_id": self.run_id,
            "run_identity_digest": self.run_identity_digest,
            "run_manifest_digest": self.run_manifest_digest,
            "phase": self.phase.value,
            "machine_cut": self.machine_cut,
            "latest_checkpoint_id": self.latest_checkpoint_id,
            "checkpoint_manifest_digest": self.checkpoint_manifest_digest,
            "pending_operation_digest": (
                None
                if self.pending_operation is None
                else self.pending_operation.digest
            ),
            "evidence_bundle_digest": (
                None
                if self.evidence_bundle_receipt is None
                else self.evidence_bundle_receipt.digest
            ),
            "outcomes": self.outcomes,
        })


@dataclass(frozen=True, slots=True)
class RunControlTransitionOutcome:
    phase: RunControlPhase

    def __post_init__(self) -> None:
        if type(self.phase) is not RunControlPhase:
            raise TypeError(
                "run control transition outcome phase must be RunControlPhase"
            )


class RunControlError(RuntimeError):
    pass


class RunControlNotFound(RunControlError):
    pass


class RunControlConflict(RunControlError):
    pass


class RunControlStaleRevision(RunControlConflict):
    pass


class RunControlIntegrityError(RunControlError):
    pass


class RunControlActionFailure(RunControlError):
    def __init__(self, receipt: RunControlReceipt) -> None:
        if not isinstance(receipt, RunControlReceipt):
            raise TypeError("run control failure requires RunControlReceipt")
        self.receipt = receipt
        super().__init__(
            f"run control {receipt.action.value} entered "
            f"{receipt.phase.value} at revision {receipt.control_revision}"
        )


class RunControlPort(Protocol):
    def execute(self, request: RunControlRequest) -> RunControlReceipt: ...


class RunControlCheckpointBundlePort(Protocol):
    @property
    def manifest(self) -> "RunCheckpointManifest": ...


class RunControlCheckpointStorePort(Protocol):
    def load(self, checkpoint_id: str) -> RunControlCheckpointBundlePort: ...


class RunControlLifecyclePort(Protocol):
    def run(
        self,
        identity: RunIdentity,
        manifest: RunLaunchManifest,
        *,
        operation_id: str,
    ) -> RunControlTransitionOutcome: ...

    def stop(
        self,
        identity: RunIdentity,
        manifest: RunLaunchManifest,
        *,
        operation_id: str,
    ) -> RunControlTransitionOutcome: ...

    def resume(
        self,
        identity: RunIdentity,
        manifest: RunLaunchManifest,
        checkpoint: "RunCheckpointManifest",
        restore_cycle_identity: DecisionCycleIdentity,
        *,
        operation_id: str,
    ) -> RunControlTransitionOutcome: ...


class RunControlReconciliationPort(Protocol):
    def reconcile(
        self,
        identity: RunIdentity,
        manifest: RunLaunchManifest,
        prepared_operation: RunControlPreparedOperation,
    ) -> EffectReconciliationVerdict: ...


class RunControlEvidencePort(Protocol):
    def evidence(
        self,
        identity: RunIdentity,
        manifest: RunLaunchManifest,
    ) -> EvidenceBundleReceipt | None: ...


__all__ = [name for name in globals() if name.startswith("RunControl") or name.startswith("Run")]
