from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from noetrium_platform.infrastructure.reliability.forensics.api.ports import ForensicWriteActorPort
from noetrium_platform.infrastructure.reliability.forensics.providers.index_db import ForensicIndexDB
from noetrium_platform.infrastructure.reliability.forensics.providers.index_projection import ProjectionBundle
from noetrium_platform.infrastructure.reliability.forensics.providers.index_sql import (
    FRESHNESS_UPSERT_SQL,
    OBJECT_UPSERT_SQL,
    OPERATION_INVOCATION_UPSERT_SQL,
    STATE_UPSERT_SQL,
)


class ForensicIndexWriteSession:
    """SQLite projection writer whose serialization is owned by a serial actor."""

    def __init__(self, db: ForensicIndexDB, writer_actor: ForensicWriteActorPort) -> None:
        if db.read_only:
            raise PermissionError("read-only forensic index cannot create write session")
        self.db = db
        self._writer_actor = writer_actor
        self._closed = False

    @contextmanager
    def _transaction_owned(self) -> Iterator[object]:
        if self._closed:
            raise RuntimeError("forensic index write session is closed")
        conn = self.db.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _write_bundle(conn, bundle: ProjectionBundle) -> None:
        conn.execute(OBJECT_UPSERT_SQL, bundle.object.values)
        if bundle.state_writer is not None:
            conn.execute(STATE_UPSERT_SQL, bundle.state_writer.values)
        if bundle.operation_invocation is not None:
            conn.execute(OPERATION_INVOCATION_UPSERT_SQL, bundle.operation_invocation.values)

    def _project_owned(self, bundle: ProjectionBundle, ledger: str, rows: int, tail_hash: str) -> None:
        with self._transaction_owned() as conn:
            self._write_bundle(conn, bundle)
            conn.execute(FRESHNESS_UPSERT_SQL, (ledger, rows, tail_hash))

    def project(self, bundle: ProjectionBundle, *, ledger: str, rows: int, tail_hash: str) -> None:
        self._writer_actor.call("project", self._project_owned, bundle, ledger, rows, tail_hash)

    def _project_batch_owned(
        self,
        bundles: tuple[ProjectionBundle, ...],
        ledger: str,
        rows: int,
        tail_hash: str,
    ) -> None:
        with self._transaction_owned() as conn:
            conn.executemany(OBJECT_UPSERT_SQL, tuple(b.object.values for b in bundles))
            state_rows = tuple(b.state_writer.values for b in bundles if b.state_writer is not None)
            if state_rows:
                conn.executemany(STATE_UPSERT_SQL, state_rows)
            operation_rows = tuple(
                b.operation_invocation.values for b in bundles if b.operation_invocation is not None
            )
            if operation_rows:
                conn.executemany(OPERATION_INVOCATION_UPSERT_SQL, operation_rows)
            conn.execute(FRESHNESS_UPSERT_SQL, (ledger, rows, tail_hash))

    def project_batch(
        self,
        bundles: tuple[ProjectionBundle, ...],
        *,
        ledger: str,
        rows: int,
        tail_hash: str,
    ) -> None:
        if not bundles:
            return
        self._writer_actor.call(
            "project-batch",
            self._project_batch_owned,
            bundles,
            ledger,
            rows,
            tail_hash,
        )

    def _upsert_owned(self, bundle: ProjectionBundle) -> None:
        with self._transaction_owned() as conn:
            self._write_bundle(conn, bundle)

    def upsert(self, bundle: ProjectionBundle) -> None:
        self._writer_actor.call("upsert", self._upsert_owned, bundle)

    def _set_freshness_owned(self, ledger: str, rows: int, tail_hash: str) -> None:
        with self._transaction_owned() as conn:
            conn.execute(FRESHNESS_UPSERT_SQL, (ledger, rows, tail_hash))

    def set_freshness(self, ledger: str, rows: int, tail_hash: str) -> None:
        self._writer_actor.call("set-freshness", self._set_freshness_owned, ledger, rows, tail_hash)

    def close(self) -> None:
        self._closed = True
