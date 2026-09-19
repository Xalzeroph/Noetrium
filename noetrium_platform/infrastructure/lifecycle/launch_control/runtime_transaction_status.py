from __future__ import annotations

from noetrium_platform.evidence.observability.status.api import HealthState, SubsystemSnapshot

from .runtime_state_contracts import RuntimeTxnPhase
from .status_ports import RuntimeControlStatusPort


class RuntimeTransactionStatusProbe:
    def __init__(self, source: RuntimeControlStatusPort) -> None:
        self._source = source

    def snapshot(self) -> SubsystemSnapshot:
        observation = self._source.observe()
        state = observation.state
        if state is None:
            return SubsystemSnapshot(
                "runtime",
                HealthState.UNKNOWN,
                "runtime control state missing",
                reason_codes=("runtime_control_state_missing",),
            )
        reason_codes: list[str] = []
        if state.phase is RuntimeTxnPhase.SUCCEEDED:
            health = HealthState.READY
        elif state.phase is RuntimeTxnPhase.FAILED:
            health = HealthState.FAILED
            reason_codes.append("runtime_transaction_failed")
        elif state.phase is RuntimeTxnPhase.RECOVERY_REQUIRED:
            health = HealthState.FAILED
            reason_codes.append("runtime_recovery_required")
        else:
            health = HealthState.DEGRADED_OPERATIONAL
            reason_codes.append("runtime_transaction_in_progress")

        detail = (
            f"phase={state.phase.value}; completed={len(state.completed_actions)}; "
            f"current={state.current_action}; mutating={state.current_mutating}"
        )
        if observation.history_errors:
            if health is not HealthState.FAILED:
                health = HealthState.DEGRADED_EVIDENCE
            detail += "; history_integrity=" + " | ".join(observation.history_errors[:3])
            reason_codes.append("runtime_history_integrity")
        elif observation.history_tail_error is not None:
            if health is not HealthState.FAILED:
                health = HealthState.DEGRADED_EVIDENCE
            descriptor = observation.history_tail_error
            detail += (
                f"; history_tail={descriptor.error_type}:{descriptor.safe_message}; "
                f"error_digest={descriptor.error_digest}"
            )
            reason_codes.append("runtime_history_tail_mismatch")

        if health is HealthState.DEGRADED_OPERATIONAL:
            next_commands = (
                "inspect the current runtime action before issuing another mutating command",
                "resume through the exact RuntimeManager plan, never skip its reconcile anchor",
            )
        elif health is HealthState.DEGRADED_EVIDENCE:
            next_commands = (
                "verify runtime history and authoritative current state",
                "do not mutate runtime state from the status path",
            )
        elif health is HealthState.FAILED:
            next_commands = ("noetrium-forensics status", "noetrium-forensics recovery-status")
        else:
            next_commands = ()
        return SubsystemSnapshot(
            "runtime",
            health,
            detail,
            evidence=tuple(observation.evidence_refs),
            next_commands=next_commands,
            reason_codes=tuple(reason_codes),
        )


__all__ = ["RuntimeTransactionStatusProbe"]
