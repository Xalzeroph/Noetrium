from __future__ import annotations

from enum import IntEnum, StrEnum


class FailureScope(StrEnum):
    """Smallest durable execution scope invalidated by a failure."""

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


class FailureDisposition(StrEnum):
    """Execution disposition declared by the failure authority.

    RETRYABLE is intentionally explicit. Unknown exceptions are never upgraded
    to retryable by the Experiment scheduler.
    """

    TERMINAL = "terminal"
    RETRYABLE = "retryable"


class ExperimentWorkloadFailure(RuntimeError):
    """Typed failure shared by environment adapters and workload runners."""

    def __init__(
        self,
        phase: str,
        code: str,
        message: str,
        *,
        scope: FailureScope = FailureScope.TASK,
        disposition: FailureDisposition = FailureDisposition.TERMINAL,
    ) -> None:
        if not phase.strip() or not code.strip():
            raise ValueError("workload failure phase and code must be non-empty")
        if not message.strip():
            raise ValueError("workload failure message must be non-empty")
        if not isinstance(scope, FailureScope):
            raise TypeError("workload failure scope must be FailureScope")
        if not isinstance(disposition, FailureDisposition):
            raise TypeError(
                "workload failure disposition must be FailureDisposition"
            )
        if (
            disposition is FailureDisposition.RETRYABLE
            and scope is not FailureScope.TASK
        ):
            raise ValueError(
                "assignment retry is valid only for task-scoped workload failures"
            )
        self.phase = phase
        self.code = code
        self.scope = scope
        self.disposition = disposition
        super().__init__(
            f"workload phase {phase} failed [{code}] "
            f"(scope={scope.value}, disposition={disposition.value}): {message}"
        )

    @property
    def may_continue_with_next_task(self) -> bool:
        return self.scope is FailureScope.TASK

    @property
    def retryable(self) -> bool:
        return self.disposition is FailureDisposition.RETRYABLE


__all__ = [
    "ExperimentWorkloadFailure",
    "FailureDisposition",
    "FailureScope",
    "FailureScopeRank",
    "failure_scope_rank",
]
