from __future__ import annotations

import sqlite3

from noetrium_platform.infrastructure.reliability.diagnostics.api import (
    DiagnosticObjectRecord,
    OperationInvocationRecord,
    StateWriterRecord,
)

from .index_db import ForensicIndexDB
from .index_queries import (
    around as read_around,
    freshness as read_freshness,
    last_writer as read_last_writer,
    locate as read_locate,
    recent_state_writers as read_recent_state_writers,
    related_to as read_related_to,
)
from .operation_index import (
    operation_invocation as read_operation_invocation,
    operations_open_at as read_operations_open_at,
    unclosed_operations as read_unclosed_operations,
)


class ForensicIndexReadSession:
    """One owned SQLite read connection for a compound diagnostic query."""

    def __init__(self, db: ForensicIndexDB) -> None:
        self.db = db
        conn = db.connect()
        conn.execute("PRAGMA query_only=ON")
        self._conn: sqlite3.Connection | None = conn

    def _connection(self) -> sqlite3.Connection:
        conn = self._conn
        if conn is None:
            raise RuntimeError("forensic index read session is closed")
        return conn

    def freshness(self) -> dict[str, tuple[int, str]]:
        return read_freshness(self._connection())

    def locate(self, object_id: str) -> DiagnosticObjectRecord | None:
        return read_locate(self._connection(), object_id)

    def last_writer(self, run_id: str, state_name: str) -> StateWriterRecord | None:
        return read_last_writer(self._connection(), run_id, state_name)

    def around(
        self,
        *,
        run_id: str,
        timestamp: float,
        seconds: float = 30.0,
    ) -> tuple[DiagnosticObjectRecord, ...]:
        return read_around(
            self._connection(),
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
        return read_recent_state_writers(
            self._connection(), run_id=run_id, before=before, limit=limit
        )

    def related_to(
        self,
        object_id: str,
        *,
        limit: int = 100,
    ) -> tuple[DiagnosticObjectRecord, ...]:
        return read_related_to(self._connection(), object_id, limit=limit)

    def operation_invocation(self, invocation_id: str) -> OperationInvocationRecord | None:
        return read_operation_invocation(self._connection(), invocation_id)

    def unclosed_operations(
        self,
        *,
        run_id: str | None = None,
        limit: int = 100,
    ) -> tuple[OperationInvocationRecord, ...]:
        return read_unclosed_operations(
            self._connection(), run_id=run_id, limit=limit
        )

    def operations_open_at(
        self,
        *,
        run_id: str,
        timestamp: float,
        limit: int = 100,
    ) -> tuple[OperationInvocationRecord, ...]:
        return read_operations_open_at(
            self._connection(),
            run_id=run_id,
            timestamp=timestamp,
            limit=limit,
        )

    def close(self) -> None:
        conn = self._conn
        if conn is None:
            return
        self._conn = None
        conn.close()

    def __enter__(self) -> ForensicIndexReadSession:
        self._connection()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = ["ForensicIndexReadSession"]
