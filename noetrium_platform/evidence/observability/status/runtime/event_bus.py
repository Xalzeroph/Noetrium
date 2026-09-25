from __future__ import annotations

from threading import RLock

from noetrium_platform.evidence.observability.status.api import (
    StatusEvent,
    StatusEventReaderPort,
    StatusEventSinkPort,
)


class InMemoryStatusEventBus(StatusEventSinkPort, StatusEventReaderPort):
    """Small process-local status bus for one composed status service.

    The port is the boundary. A durable or distributed event backend can be
    substituted by the composition root without changing producers or status
    projections.
    """

    def __init__(self) -> None:
        self._events: dict[str, StatusEvent] = {}
        self._lock = RLock()

    def publish_status(self, event: StatusEvent) -> None:
        with self._lock:
            self._events[event.subsystem] = event

    def latest_status(self, subsystem: str) -> StatusEvent | None:
        with self._lock:
            return self._events.get(subsystem)


__all__ = ["InMemoryStatusEventBus"]
