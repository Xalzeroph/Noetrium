from __future__ import annotations

from typing import Protocol, TypeVar

from noetrium_platform.research.execution.workflow.api import TrialCycleExecution
from noetrium_platform.capabilities.participant.core.api import (
    BoundParticipants,
    ParticipantSessionBinding,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonInput


TaskT = TypeVar("TaskT")

from .contracts import ExperimentSpec


class ExperimentComponentBindingPort(Protocol):
    def bind(self, spec: ExperimentSpec, context: ExecutionContext) -> BoundParticipants: ...


class ExperimentTrialCycleExecutorPort(Protocol):
    def execute(
        self,
        *,
        bound: BoundParticipants,
        participant_sessions: tuple[ParticipantSessionBinding, ...],
        context: ExecutionContext,
        task: TaskT,
        input_kind: str,
        input_payload: JsonInput,
    ) -> TrialCycleExecution: ...


__all__ = ["ExperimentComponentBindingPort", "ExperimentTrialCycleExecutorPort"]
