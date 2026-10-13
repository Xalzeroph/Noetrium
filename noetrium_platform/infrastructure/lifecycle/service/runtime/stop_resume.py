from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .contracts import ServicePhase
from .service_state_contracts import ServiceSupervisorState


class ServiceStopDisposition(StrEnum):
    NO_PROCESS_EFFECT = "no_process_effect"
    STOP_PERSISTED_PROCESS = "stop_persisted_process"
    BLOCK_EFFECT_UNCERTAIN = "block_effect_uncertain"
    BLOCK_RECOVERY_REQUIRED = "block_recovery_required"


@dataclass(frozen=True, slots=True)
class ServiceStopResumeDecision:
    disposition: ServiceStopDisposition
    reason: str

    @property
    def blocked(self) -> bool:
        return self.disposition in {
            ServiceStopDisposition.BLOCK_EFFECT_UNCERTAIN,
            ServiceStopDisposition.BLOCK_RECOVERY_REQUIRED,
        }


class ServiceStopRecoveryRequired(RuntimeError):
    def __init__(self, state: ServiceSupervisorState, decision: ServiceStopResumeDecision) -> None:
        super().__init__(f"service stop blocked at phase {state.phase.value}: {decision.reason}")
        self.state = state
        self.decision = decision


def decide_service_stop_resume(state: ServiceSupervisorState) -> ServiceStopResumeDecision:
    phase = state.phase

    if phase is ServicePhase.START_CHILD and state.process is None:
        return ServiceStopResumeDecision(
            ServiceStopDisposition.BLOCK_EFFECT_UNCERTAIN,
            "child-start effect is uncertain and no exact process identity exists to stop safely",
        )

    if phase in {ServicePhase.RECOVERY_REQUIRED, ServicePhase.FAILED}:
        return ServiceStopResumeDecision(
            ServiceStopDisposition.BLOCK_RECOVERY_REQUIRED,
            "recovery evidence must be reconciled before changing terminal service state",
        )

    if state.process is not None:
        if phase in {
            ServicePhase.START_CHILD,
            ServicePhase.WAIT_READY,
            ServicePhase.RUNNING,
            ServicePhase.DRAINING,
            ServicePhase.STOPPING,
        }:
            return ServiceStopResumeDecision(
                ServiceStopDisposition.STOP_PERSISTED_PROCESS,
                "persisted process identity permits exact idempotent stop reconciliation",
            )
        return ServiceStopResumeDecision(
            ServiceStopDisposition.BLOCK_RECOVERY_REQUIRED,
            f"phase {phase.value} unexpectedly retains a process identity",
        )

    if phase in {
        ServicePhase.NEW,
        ServicePhase.VERIFY_CONTRACT,
        ServicePhase.RECONCILE_PRIOR,
        ServicePhase.EXITED,
    }:
        return ServiceStopResumeDecision(
            ServiceStopDisposition.NO_PROCESS_EFFECT,
            "no unresolved process side effect is recorded",
        )

    if phase in {ServicePhase.WAIT_READY, ServicePhase.RUNNING, ServicePhase.STOPPING, ServicePhase.DRAINING}:
        return ServiceStopResumeDecision(
            ServiceStopDisposition.BLOCK_RECOVERY_REQUIRED,
            "phase requires a persisted process identity but none is available",
        )

    return ServiceStopResumeDecision(
        ServiceStopDisposition.BLOCK_RECOVERY_REQUIRED,
        f"service phase {phase.value} has no safe automatic stop transition",
    )


__all__ = [
    "ServiceStopDisposition",
    "ServiceStopRecoveryRequired",
    "ServiceStopResumeDecision",
    "decide_service_stop_resume",
]
