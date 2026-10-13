from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import OperationResult, OperationStatus


@dataclass(frozen=True, slots=True)
class RunCleanupReport:
    results: tuple[OperationResult, ...]

    def __post_init__(self) -> None:
        if type(self.results) is not tuple or any(
            not isinstance(row, OperationResult) for row in self.results
        ):
            raise TypeError("run cleanup results must be an OperationResult tuple")

    @property
    def failures(self) -> tuple[OperationResult, ...]:
        return tuple(
            row for row in self.results
            if row.status is not OperationStatus.SUCCEEDED
        )


class RunCleanupFailure(RuntimeError):
    def __init__(self, report: RunCleanupReport, *, trial_completed: bool) -> None:
        if not isinstance(report, RunCleanupReport):
            raise TypeError("run cleanup failure requires RunCleanupReport")
        if type(trial_completed) is not bool:
            raise TypeError("trial_completed must be bool")
        self.report = report
        self.trial_completed = trial_completed
        super().__init__(
            "run cleanup failed: "
            f"failures={len(report.failures)} trial_completed={trial_completed}"
        )


def attach_cleanup_note(error: BaseException, report: RunCleanupReport) -> None:
    if not isinstance(error, BaseException):
        raise TypeError("cleanup note target must be an exception")
    if not isinstance(report, RunCleanupReport):
        raise TypeError("cleanup note requires RunCleanupReport")
    if not report.results:
        return
    try:
        error.add_note(
            "run cleanup after primary failure: "
            f"results={len(report.results)} failures={len(report.failures)}"
        )
    except AttributeError:
        pass


__all__ = ["RunCleanupFailure", "RunCleanupReport", "attach_cleanup_note"]
