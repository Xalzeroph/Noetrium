from __future__ import annotations

from threading import RLock

from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.evidence.observability.logging.query.api import LogQueryPort
from noetrium_platform.evidence.observability.logging.record.api import LogLevel, LogRecord
from noetrium_platform.evidence.observability.logging.sink.api import LogSinkPort
from noetrium_platform.foundation.scope.api import ScopeIdentity


class InMemoryLogStore(LogSinkPort, LogQueryPort):
    """Volatile storage adapter satisfying the logging write/read seams."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._rows: list[LogRecord] = []

    def append(self, record: LogRecord) -> None:
        with self._lock:
            self._rows.append(record)

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
    ) -> tuple[LogRecord, ...]:
        if limit <= 0:
            return ()
        rank = {level: index for index, level in enumerate(LogLevel)}
        with self._lock:
            rows = list(reversed(self._rows))
        selected: list[LogRecord] = []
        for row in rows:
            if scope is not None and scope not in row.address.scope_path:
                continue
            if system is not None and system not in row.address.system_path:
                continue
            if component_id is not None and row.address.component_id != component_id:
                continue
            if trace_id is not None and row.address.trace_id != trace_id:
                continue
            if level_at_least is not None and rank[row.level] < rank[level_at_least]:
                continue
            if event is not None and row.event != event:
                continue
            selected.append(row)
            if len(selected) >= limit:
                break
        return tuple(selected)


__all__ = ["InMemoryLogStore"]
