from __future__ import annotations

from typing import Protocol

from noetrium_platform.evidence.observability.logging.sink.api import LogSinkPort


class LogRoutingPort(LogSinkPort, Protocol):
    """Routing seam that accepts records and dispatches them to configured sinks."""


__all__ = ["LogRoutingPort"]
