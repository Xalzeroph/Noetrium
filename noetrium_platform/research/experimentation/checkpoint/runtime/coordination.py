from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from .capture import RunCheckpointCapture
from ..api.contracts import RunCheckpointStore
from .identity import CHECKPOINT_STORE_IDENTITY
from ..api.results import RunCheckpointResult, RunRestoreResult
from .restore import RunCheckpointRestorer
from .validation import RunCheckpointIdentityMismatch
from noetrium_platform.capabilities.participant.core.api import BoundParticipants, ParticipantSessionBinding
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.execution.workflow.api import OperationDispatchPort
from noetrium_platform.capabilities.participant.core.api.runtime_ports import ParticipantCheckpointOperationsPort
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec


class RunCheckpointCoordinator:
    """Façade over generic participant checkpoint capture and restore."""

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        store: RunCheckpointStore,
        participant_checkpoints: ParticipantCheckpointOperationsPort,
    ) -> None:
        self._capture = RunCheckpointCapture(dispatcher, store, participant_checkpoints)
        self._restore = RunCheckpointRestorer(dispatcher, store, participant_checkpoints)

    def checkpoint(
        self,
        *,
        spec: ExperimentSpec,
        bound: BoundParticipants,
        participant_sessions: tuple[ParticipantSessionBinding, ...],
        context: ExecutionContext,
        cycle_identity: DecisionCycleIdentity,
    ) -> RunCheckpointResult:
        return self._capture.capture(
            spec=spec,
            bound=bound,
            participant_sessions=participant_sessions,
            context=context,
            cycle_identity=cycle_identity,
        )

    def restore(
        self,
        checkpoint_id: str,
        *,
        spec: ExperimentSpec,
        bound: BoundParticipants,
        participant_sessions: tuple[ParticipantSessionBinding, ...],
        context: ExecutionContext,
        cycle_identity: DecisionCycleIdentity,
    ) -> RunRestoreResult:
        return self._restore.restore(
            checkpoint_id,
            spec=spec,
            bound=bound,
            participant_sessions=participant_sessions,
            context=context,
            cycle_identity=cycle_identity,
        )


__all__ = [
    "CHECKPOINT_STORE_IDENTITY",
    "RunCheckpointCoordinator",
    "RunCheckpointIdentityMismatch",
    "RunCheckpointResult",
    "RunRestoreResult",
]
