from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import JsonValue, OperationResult, OperationStatus


@dataclass(frozen=True, slots=True)
class RunCleanupReport:
    results: tuple[OperationResult[JsonValue], ...]

    @property
    def failures(self) -> tuple[OperationResult[JsonValue], ...]:
        return tuple(x for x in self.results if x.status is not OperationStatus.SUCCEEDED)


class RunCleanupFailure(RuntimeError):
    def __init__(self, report: RunCleanupReport, *, trial_completed: bool) -> None:
        self.report = report
        self.trial_completed = trial_completed
        ids = ",".join(x.operation_id for x in report.failures)
        super().__init__(f"study cleanup failed after component execution: {ids}")


class RunClosed(RuntimeError):
    pass


class RunRecoveryRequired(RuntimeError):
    pass


__all__ = ["RunCleanupFailure", "RunCleanupReport", "RunClosed", "RunRecoveryRequired"]
