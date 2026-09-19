from __future__ import annotations

from noetrium_platform.evidence.observability.status.api import (
    HealthState,
    StatusEventReaderPort,
    SubsystemSnapshot,
)


class RecoveryLeaseStatusProbe:
    def __init__(
        self,
        source: StatusEventReaderPort,
    ) -> None:
        self._source = source

    def snapshot(self) -> SubsystemSnapshot:
        event = self._source.latest_status("recovery_lease")
        if event is None:
            return SubsystemSnapshot(
                "recovery_lease",
                HealthState.UNKNOWN,
                "recovery lease status event unavailable",
                reason_codes=("status_event_missing",),
            )
        return event.snapshot()


__all__ = ["RecoveryLeaseStatusProbe"]
