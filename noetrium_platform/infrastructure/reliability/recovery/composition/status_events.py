from __future__ import annotations

import time
from typing import Callable

from noetrium_platform.evidence.observability.status.api import (
    HealthState,
    StatusEvent,
    StatusEventReaderPort,
    StatusEventSinkPort,
    SubsystemStatusProbePort,
)
from noetrium_platform.evidence.observability.status.runtime import (
    InMemoryStatusEventBus,
    RecoveryLeaseStatusProbe,
)

from ..api.ports import RecoveryLeaseStatusPort


class RecoveryLeaseStatusEventPublisher:
    """Translate recovery ownership into the independent observation plane."""

    def __init__(
        self,
        source: RecoveryLeaseStatusPort,
        sink: StatusEventSinkPort,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._source = source
        self._sink = sink
        self._clock = clock

    def publish(self) -> None:
        now = self._clock()
        lease = self._source.read()
        if lease is None:
            self._sink.publish_status(StatusEvent(
                "recovery_lease",
                HealthState.READY,
                "no active recovery owner",
                observed_at=now,
            ))
            return
        remaining = lease.expires_at - now
        if remaining <= 0:
            self._sink.publish_status(StatusEvent(
                "recovery_lease",
                HealthState.FAILED,
                f"expired recovery lease owner={lease.owner_id}",
                evidence=self._source.evidence_refs(),
                next_commands=("inspect stale recovery owner before acquiring a new lease",),
                reason_codes=("recovery_lease_expired",),
                observed_at=now,
            ))
            return
        self._sink.publish_status(StatusEvent(
            "recovery_lease",
            HealthState.READY,
            f"owner={lease.owner_id}; expires_in={remaining:.1f}s",
            evidence=self._source.evidence_refs(),
            observed_at=now,
        ))


class RecoveryLeaseStatusEventProjection(SubsystemStatusProbePort):
    """Refresh a producer event, then consume it through the status port."""

    def __init__(
        self,
        publisher: RecoveryLeaseStatusEventPublisher,
        reader: StatusEventReaderPort,
    ) -> None:
        self._publisher = publisher
        self._probe = RecoveryLeaseStatusProbe(reader)

    def snapshot(self):
        self._publisher.publish()
        return self._probe.snapshot()


def compose_recovery_lease_status_probe(
    source: RecoveryLeaseStatusPort,
    *,
    clock: Callable[[], float] = time.time,
) -> SubsystemStatusProbePort:
    """Freeze reliability-to-observability wiring in a composition root."""

    bus = InMemoryStatusEventBus()
    publisher = RecoveryLeaseStatusEventPublisher(source, bus, clock=clock)
    return RecoveryLeaseStatusEventProjection(publisher, bus)


__all__ = [
    "RecoveryLeaseStatusEventProjection",
    "RecoveryLeaseStatusEventPublisher",
    "compose_recovery_lease_status_probe",
]
