from __future__ import annotations

from noetrium_platform.evidence.observability.status.api import HealthState, SubsystemSnapshot

from .contracts import ServicePhase
from .status_ports import ServiceOperationalStatusPort


class ServiceOperationalStatusProbe:
    def __init__(self, service_id: str, source: ServiceOperationalStatusPort) -> None:
        self._service_id = service_id
        self._source = source

    def snapshot(self) -> SubsystemSnapshot:
        service_id = self._service_id
        observation = self._source.observe()
        state = observation.state
        if state is None:
            return SubsystemSnapshot(
                f"service:{service_id}",
                HealthState.UNKNOWN,
                "service state missing",
                reason_codes=("service_state_missing",),
            )
        reason_codes: list[str] = []
        if state.phase is ServicePhase.RUNNING:
            health = HealthState.READY
        elif state.phase is ServicePhase.RECOVERY_REQUIRED:
            health = HealthState.FAILED
            reason_codes.append("service_recovery_required")
        elif state.phase in {ServicePhase.EXITED, ServicePhase.FAILED}:
            health = HealthState.FAILED
            reason_codes.append(f"service_phase_{state.phase.value}")
        else:
            health = HealthState.DEGRADED_OPERATIONAL
            reason_codes.append(f"service_phase_{state.phase.value}")

        refs = list(observation.evidence_refs)
        refs.extend(
            value
            for value in (
                state.ready_evidence_ref,
                state.stdout_capture_ref,
                state.stderr_capture_ref,
            )
            if value
        )
        detail = f"phase={state.phase.value}; attempt={state.attempt}"
        unresolved = observation.unresolved_start_intents
        if len(unresolved) > 1:
            health = HealthState.FAILED
            detail += f"; start_intent_integrity=multiple_unresolved:{len(unresolved)}"
            reason_codes.append("multiple_unresolved_start_intents")
        elif unresolved:
            intent = unresolved[0]
            detail += f"; start_intent={intent.phase.value}:{intent.intent_id}"
            reason_codes.append("unresolved_start_intent")
            if intent.recovery_handle is not None:
                refs.append(
                    f"service-start-recovery:{intent.recovery_handle.provider_schema}:"
                    f"{intent.recovery_handle.payload_sha256}"
                )
            if intent.process is not None:
                refs.append(f"start-intent-process:{intent.process.pid}:{intent.process.start_identity}")

        if health is HealthState.DEGRADED_OPERATIONAL:
            next_commands = (
                f"inspect/reconcile exact service start state for {service_id}",
                "do not issue a second start while a start intent is unresolved",
            )
        elif health is HealthState.FAILED:
            next_commands = (
                (f"noetrium-forensics debug-snapshot {state.last_failure_id}",)
                if state.last_failure_id
                else (f"inspect exact service state and unresolved start intent for {service_id}",)
            )
        else:
            next_commands = ()
        return SubsystemSnapshot(
            f"service:{service_id}",
            health,
            detail,
            evidence=tuple(refs),
            failure_id=state.last_failure_id,
            next_commands=next_commands,
            reason_codes=tuple(reason_codes),
        )


__all__ = ["ServiceOperationalStatusProbe"]
