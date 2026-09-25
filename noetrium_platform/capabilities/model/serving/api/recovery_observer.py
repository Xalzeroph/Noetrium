from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .recovery import RecoveryStep


class DurableRecoveryObserverPort(Protocol):
    """Side-plane lifecycle observer; delivery failure must never alter recovery truth."""

    def attempt_started(self, *, cause: str) -> None: ...

    def step_started(self, step: RecoveryStep) -> None: ...

    def step_finished(self, step: RecoveryStep, *, result: str) -> None: ...

    def attempt_finished(self, *, result: str) -> None: ...


@dataclass(frozen=True, slots=True)
class RecoveryObserverFailure:
    stage: str
    error_type: str

    @classmethod
    def from_exception(cls, stage: str, exc: BaseException) -> "RecoveryObserverFailure":
        return cls(stage=stage, error_type=type(exc).__qualname__)


class DurableRecoveryObserverFailureSink(Protocol):
    def record(self, failure: RecoveryObserverFailure) -> None: ...


__all__ = [
    "DurableRecoveryObserverFailureSink",
    "DurableRecoveryObserverPort",
    "RecoveryObserverFailure",
]
