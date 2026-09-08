from __future__ import annotations

from noetrium_platform.evidence.observability.logging.record.api import LogRecord
from noetrium_platform.evidence.observability.logging.sink.api import LogSinkPort
from noetrium_platform.evidence.observability.logging.routing.api import LogRoutingPort


class FanoutLogSink(LogRoutingPort):
    """Routing adapter that delivers one record to injected sink adapters."""

    def __init__(self, sinks: tuple[LogSinkPort, ...]) -> None:
        self._sinks = tuple(sinks)

    def append(self, record: LogRecord) -> None:
        for sink in self._sinks:
            sink.append(record)


__all__ = ["FanoutLogSink"]
