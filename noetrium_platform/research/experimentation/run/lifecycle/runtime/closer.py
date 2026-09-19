from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from ..api.contracts import RunCleanupFailure, RunCleanupReport
from ...identity.api import RunIdentity
from noetrium_platform.capabilities.participant.core.api import ParticipantSessionBinding
from noetrium_platform.capabilities.participant.core.api.runtime_ports import ParticipantSessionLifecyclePort
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec


class RunCloser:
    """Closes generic participants in exact reverse dependency/open order."""

    def __init__(
        self,
        *,
        spec: ExperimentSpec,
        identity: RunIdentity,
        participant_sessions: tuple[ParticipantSessionBinding, ...],
        lifecycle: ParticipantSessionLifecyclePort,
    ) -> None:
        self._spec = spec
        self._identity = identity
        self._participant_sessions = participant_sessions
        self._lifecycle = lifecycle

    def close(self, context: ExecutionContext | None, *, trial_completed: bool) -> RunCleanupReport:
        root = context or ExecutionContext(
            self._identity.run_id, self._identity.trace_id, "run-close", study_id=self._spec.study_id
        )
        rows = tuple(
            self._lifecycle.close_participant(binding, root, self._identity.session_id)
            for binding in reversed(self._participant_sessions)
        )
        report = RunCleanupReport(rows)
        if report.failures:
            raise RunCleanupFailure(report, trial_completed=trial_completed)
        return report


__all__ = ["RunCloser"]
