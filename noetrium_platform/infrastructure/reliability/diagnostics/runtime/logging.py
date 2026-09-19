from __future__ import annotations

from noetrium_platform.evidence.observability.logging.query.api import LogQueryPort
from noetrium_platform.evidence.observability.logging.record.api import LogLevel, LogRecord
from noetrium_platform.foundation.scope.api import ScopeIdentity
from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.infrastructure.reliability.diagnostics.api.logging import DiagnosticLogQueryPort


class DiagnosticLogQueryAdapter(DiagnosticLogQueryPort):
    """Pure read adapter. Diagnostics owns no log storage and no log mutation authority."""

    def __init__(self, query: LogQueryPort) -> None:
        self._query = query

    def query_logs(
        self,
        *,
        scope: ScopeIdentity | None = None,
        system: SystemIdentity | None = None,
        component_id: str | None = None,
        trace_id: str | None = None,
        level_at_least: LogLevel | None = None,
        event: str | None = None,
        limit: int = 1000,
    ) -> tuple[LogRecord, ...]:
        return self._query.query(
            scope=scope,
            system=system,
            component_id=component_id,
            trace_id=trace_id,
            level_at_least=level_at_least,
            event=event,
            limit=limit,
        )


__all__ = ["DiagnosticLogQueryAdapter"]
