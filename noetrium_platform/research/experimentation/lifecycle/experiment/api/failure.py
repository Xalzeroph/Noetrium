from __future__ import annotations

from enum import IntEnum, StrEnum


class FailureScope(StrEnum):
    """Smallest durable execution scope invalidated by a failure.

    A task-scoped failure may be represented as a task result.  A wider scope
    invalidates the state that later tasks would rely on and must therefore
    escape the task loop for branch/run-level cleanup and recovery.
    """

    TASK = "task"
    PARTICIPANT = "participant"
    BRANCH = "branch"
    RUN = "run"
    HOST = "host"


class FailureScopeRank(IntEnum):
    TASK = 0
    PARTICIPANT = 1
    BRANCH = 2
    RUN = 3
    HOST = 4


def failure_scope_rank(scope: FailureScope) -> FailureScopeRank:
    return FailureScopeRank[scope.name]


class ExperimentWorkloadFailure(RuntimeError):
    """Typed failure shared by environment adapters and workload runners."""

    def __init__(
        self,
        phase: str,
        code: str,
        message: str,
        *,
        scope: FailureScope = FailureScope.TASK,
    ) -> None:
        if not phase.strip() or not code.strip():
            raise ValueError("workload failure phase and code must be non-empty")
        if not message.strip():
            raise ValueError("workload failure message must be non-empty")
        self.phase = phase
        self.code = code
        self.scope = scope
        super().__init__(
            f"workload phase {phase} failed [{code}] "
            f"(scope={scope.value}): {message}"
        )

    @property
    def may_continue_with_next_task(self) -> bool:
        return self.scope is FailureScope.TASK


__all__ = [
    "ExperimentWorkloadFailure",
    "FailureScope",
    "FailureScopeRank",
    "failure_scope_rank",
]
