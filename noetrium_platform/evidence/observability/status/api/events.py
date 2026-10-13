from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Protocol

from .contracts import HealthState, SubsystemSnapshot


@dataclass(frozen=True, slots=True)
class StatusEvent:
    """Storage-neutral observation event consumed by status projections.

    Producers publish only the stable observation contract. The producer's
    state store, lease implementation, and failure taxonomy remain outside
    the observability runtime plane.
    """

    subsystem: str
    state: HealthState
    summary: str
    evidence: tuple[str, ...] = ()
    next_commands: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    observed_at: float = field(default_factory=time.time)

    def snapshot(self) -> SubsystemSnapshot:
        return SubsystemSnapshot(
            self.subsystem,
            self.state,
            self.summary,
            evidence=self.evidence,
            next_commands=self.next_commands,
            reason_codes=self.reason_codes,
        )


class StatusEventSinkPort(Protocol):
    def publish_status(self, event: StatusEvent) -> None: ...


class StatusEventReaderPort(Protocol):
    def latest_status(self, subsystem: str) -> StatusEvent | None: ...


__all__ = ["StatusEvent", "StatusEventReaderPort", "StatusEventSinkPort"]
