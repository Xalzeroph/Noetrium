from __future__ import annotations

from typing import Protocol

from noetrium_platform.evidence.observability.logging.record.api import LogRecord


class LogSinkPort(Protocol):
    """Write seam; adapters decide delivery and durability policy."""

    def append(self, record: LogRecord) -> None: ...


__all__ = ["LogSinkPort"]
