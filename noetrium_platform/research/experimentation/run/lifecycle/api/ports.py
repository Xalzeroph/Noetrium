from __future__ import annotations

from typing import Protocol, TypeVar

from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.execution.decision.cycle_result import DecisionCycleResult
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.capabilities.participant.core.api import ParticipantSessionBinding
from noetrium_platform.capabilities.participant.core.api.runtime_ports import ParticipantSessionLifecyclePort
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonInput, JsonValue, OperationResult
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity

from .contracts import RunCleanupReport


TaskT = TypeVar("TaskT")


class RunCycleExecutionPort(Protocol):
    """Lifecycle-facing view of one completed run cycle."""

    @property
    def result(self) -> DecisionCycleResult: ...

    @property
    def final_context(self) -> ExecutionContext: ...

    @property
    def checkpoint_id(self) -> str | None: ...


class RunCycleExecutorPort(Protocol):
    """Narrow behavior needed by a lifecycle-owned run session."""

    def execute(
        self,
        *,
        task: TaskT,
        input_kind: str,
        input_payload: JsonInput,
        cycle_identity: DecisionCycleIdentity,
        previous_context: ExecutionContext | None,
    ) -> RunCycleExecutionPort: ...


class RunLifetimePort(Protocol):
    """Process-local driver over a journal-authoritative run Runtime Machine."""

    def close(
        self,
        context: ExecutionContext,
        *,
        trial_completed: bool,
    ) -> RunCleanupReport: ...


class RunSessionPort(Protocol):
    """Stable lifecycle-owned surface for an open run."""

    @property
    def latest_checkpoint_id(self) -> str | None: ...

    @property
    def requires_recovery(self) -> bool: ...

    def execute(
        self,
        *,
        task: TaskT,
        input_kind: str = "input",
        input_payload: JsonInput = None,
        cycle_identity: DecisionCycleIdentity,
    ) -> DecisionCycleResult: ...

    def close(self) -> RunCleanupReport: ...


__all__ = [
    "RunCycleExecutionPort",
    "RunCycleExecutorPort",
    "RunLifetimePort",
    "RunSessionPort",
]
