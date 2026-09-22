from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionObservationState, PersistentSessionStatusProbePort
from noetrium_platform.evidence.observability.status.api import HealthState, SubsystemSnapshot


class PersistentSessionHealthProbe:
    def __init__(self, source: PersistentSessionStatusProbePort) -> None:
        self._source = source

    def snapshot(self) -> SubsystemSnapshot:
        observation = self._source.observe()
        if observation.state is PersistentSessionObservationState.EXACT:
            state = HealthState.READY
        elif observation.state in {
            PersistentSessionObservationState.MISSING,
            PersistentSessionObservationState.DRIFT,
            PersistentSessionObservationState.UNAVAILABLE,
        }:
            state = HealthState.DEGRADED_OPERATIONAL
        else:
            state = HealthState.UNKNOWN

        attach = " ".join(observation.attach_argv) if observation.attach_argv else ""
        next_commands = (f"attach exact controller: {attach}",) if attach and state is HealthState.READY else ()
        if state is HealthState.DEGRADED_OPERATIONAL:
            next_commands = (
                "inspect runtime/service status before recreating the persistent controller",
                "never infer service death from persistent-session absence",
            )
        return SubsystemSnapshot(
            "server_session",
            state,
            observation.summary,
            evidence=tuple(observation.evidence_refs),
            next_commands=next_commands,
            reason_codes=(
                (observation.reason_code,)
                if observation.reason_code and state is not HealthState.READY
                else ()
            ),
        )


__all__ = ["PersistentSessionHealthProbe"]
