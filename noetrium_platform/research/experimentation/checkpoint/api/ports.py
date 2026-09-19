from __future__ import annotations

from typing import Protocol

from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.capabilities.participant.core.api import BoundParticipants, ParticipantSessionBinding
from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from .results import RunCheckpointResult, RunRestoreResult


class RunCheckpointCoordinatorPort(Protocol):
    def checkpoint(
        self,
        *,
        spec: ExperimentSpec,
        bound: BoundParticipants,
        participant_sessions: tuple[ParticipantSessionBinding, ...],
        context: ExecutionContext,
        cycle_identity: DecisionCycleIdentity,
    ) -> RunCheckpointResult: ...

    def restore(
        self,
        checkpoint_id: str,
        *,
        spec: ExperimentSpec,
        bound: BoundParticipants,
        participant_sessions: tuple[ParticipantSessionBinding, ...],
        context: ExecutionContext,
        cycle_identity: DecisionCycleIdentity,
    ) -> RunRestoreResult: ...


__all__ = ["RunCheckpointCoordinatorPort"]
