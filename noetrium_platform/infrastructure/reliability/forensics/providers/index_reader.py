from __future__ import annotations

from noetrium_platform.infrastructure.reliability.diagnostics.api import (
    DiagnosticObjectRecord,
    OperationInvocationRecord,
    StateWriterRecord,
)

from .index_db import ForensicIndexDB
from .index_session import ForensicIndexReadSession


class ForensicIndexReader:
    """One-shot query facade over explicit compound-query read sessions."""

    def __init__(self, db: ForensicIndexDB) -> None:
        self.db = db

    def session(self) -> ForensicIndexReadSession:
        return ForensicIndexReadSession(self.db)

    def freshness(self) -> dict[str, tuple[int, str]]:
        with self.session() as session:
            return session.freshness()

    def locate(self, object_id: str) -> DiagnosticObjectRecord | None:
        with self.session() as session:
            return session.locate(object_id)

    def last_writer(self, run_id: str, state_name: str) -> StateWriterRecord | None:
        with self.session() as session:
            return session.last_writer(run_id, state_name)

    def around(
        self,
        *,
        run_id: str,
        timestamp: float,
        seconds: float = 30.0,
    ) -> tuple[DiagnosticObjectRecord, ...]:
        with self.session() as session:
            return session.around(
                run_id=run_id,
                timestamp=timestamp,
                seconds=seconds,
            )

    def recent_state_writers(
        self,
        *,
        run_id: str,
        before: float,
        limit: int = 12,
    ) -> tuple[StateWriterRecord, ...]:
        with self.session() as session:
            return session.recent_state_writers(
                run_id=run_id,
                before=before,
                limit=limit,
            )

    def related_to(
        self,
        object_id: str,
        *,
        limit: int = 100,
    ) -> tuple[DiagnosticObjectRecord, ...]:
        with self.session() as session:
            return session.related_to(object_id, limit=limit)

    def operation_invocation(self, invocation_id: str) -> OperationInvocationRecord | None:
        with self.session() as session:
            return session.operation_invocation(invocation_id)

    def unclosed_operations(
        self,
        *,
        run_id: str | None = None,
        limit: int = 100,
    ) -> tuple[OperationInvocationRecord, ...]:
        with self.session() as session:
            return session.unclosed_operations(run_id=run_id, limit=limit)

    def operations_open_at(
        self,
        *,
        run_id: str,
        timestamp: float,
        limit: int = 100,
    ) -> tuple[OperationInvocationRecord, ...]:
        with self.session() as session:
            return session.operations_open_at(
                run_id=run_id,
                timestamp=timestamp,
                limit=limit,
            )


__all__ = ["ForensicIndexReadSession", "ForensicIndexReader"]
