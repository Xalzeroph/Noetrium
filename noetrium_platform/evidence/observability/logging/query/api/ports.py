from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.evidence.observability.logging.record.api import LogLevel, LogRecord
from noetrium_platform.foundation.scope.api import ScopeIdentity


class LogQueryPort(Protocol):
    """Read seam; query adapters own filtering and projection policy."""

    def query(
        self,
        *,
        scope: ScopeIdentity | None = None,
        system: SystemIdentity | None = None,
        component_id: str | None = None,
        trace_id: str | None = None,
        level_at_least: LogLevel | None = None,
        event: str | None = None,
        limit: int = 1000,
    ) -> tuple[LogRecord, ...]: ...


__all__ = ["LogQueryPort"]
