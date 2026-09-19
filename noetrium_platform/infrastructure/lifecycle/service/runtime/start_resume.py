from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .contracts import ServicePhase
from .service_state_contracts import ServiceSupervisorState


class ServiceStartDisposition(StrEnum):
    SAFE_TO_START_OR_RECONCILE = "safe_to_start_or_reconcile"
    RECONCILE_PERSISTED_PROCESS = "reconcile_persisted_process"
    BLOCK_EFFECT_UNCERTAIN = "block_effect_uncertain"
    BLOCK_RECOVERY_REQUIRED = "block_recovery_required"


@dataclass(frozen=True, slots=True)
class ServiceStartResumeDecision:
    disposition: ServiceStartDisposition
    reason: str

    @property
    def blocked(self) -> bool:
        return self.disposition in {
            ServiceStartDisposition.BLOCK_EFFECT_UNCERTAIN,
            ServiceStartDisposition.BLOCK_RECOVERY_REQUIRED,
        }


class ServiceStartRecoveryRequired(RuntimeError):
    def __init__(self, state: ServiceSupervisorState, decision: ServiceStartResumeDecision) -> None:
        super().__init__(
            f"service start blocked at phase {state.phase.value}: {decision.reason}"
        )
        self.state = state
        self.decision = decision


def decide_service_start_resume(state: ServiceSupervisorState) -> ServiceStartResumeDecision:
    phase = state.phase

    if phase is ServicePhase.START_CHILD:
        if state.process is None:
            return ServiceStartResumeDecision(
                ServiceStartDisposition.BLOCK_EFFECT_UNCERTAIN,
                "child-start side effect may have happened before process identity was persisted; reconcile before retry",
            )
        return ServiceStartResumeDecision(
            ServiceStartDisposition.RECONCILE_PERSISTED_PROCESS,
            "child process identity is persisted; exact reconciliation is required before readiness",
        )

    if phase in {ServicePhase.STOPPING, ServicePhase.DRAINING}:
        return ServiceStartResumeDecision(
            ServiceStartDisposition.BLOCK_EFFECT_UNCERTAIN,
            "prior stop/drain side effect is unresolved; starting another process could duplicate ownership",
        )

    if phase in {ServicePhase.RECOVERY_REQUIRED, ServicePhase.FAILED}:
        return ServiceStartResumeDecision(
            ServiceStartDisposition.BLOCK_RECOVERY_REQUIRED,
            "service is explicitly recovery-gated and cannot be auto-started",
        )

    if phase in {ServicePhase.RUNNING, ServicePhase.WAIT_READY}:
        if state.process is None:
            return ServiceStartResumeDecision(
                ServiceStartDisposition.BLOCK_RECOVERY_REQUIRED,
                "running/readiness phase lacks persisted process identity",
            )
        return ServiceStartResumeDecision(
            ServiceStartDisposition.RECONCILE_PERSISTED_PROCESS,
            "persisted live-process identity must be exactly reconciled",
        )

    if phase in {
        ServicePhase.NEW,
        ServicePhase.VERIFY_CONTRACT,
        ServicePhase.RECONCILE_PRIOR,
        ServicePhase.EXITED,
    }:
        return ServiceStartResumeDecision(
            ServiceStartDisposition.SAFE_TO_START_OR_RECONCILE,
            "no unresolved external process side effect is recorded",
        )

    return ServiceStartResumeDecision(
        ServiceStartDisposition.BLOCK_RECOVERY_REQUIRED,
        f"service phase {phase.value} has no safe automatic start transition",
    )


__all__ = [
    "ServiceStartDisposition",
    "ServiceStartRecoveryRequired",
    "ServiceStartResumeDecision",
    "decide_service_start_resume",
]
