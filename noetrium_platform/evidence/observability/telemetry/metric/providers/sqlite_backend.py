from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
from threading import Lock
from weakref import WeakSet

from noetrium_platform.evidence.observability.telemetry.metric.api import (
    TelemetryStorageReadRow,
    TelemetryStorageWriteRow,
    TelemetryWriteActorPort,
)

from .sqlite_reader import TelemetryReadSession
from .sqlite_schema import initialize_telemetry_schema
from .sqlite_writer import TelemetryWriteSession


class TelemetrySQLiteBackend:
    """SQLite telemetry persistence with one injected actor writer authority."""

    def __init__(self, path: Path, *, writer_actor: TelemetryWriteActorPort) -> None:
        self.path = path
        self._writer_actor = writer_actor
        self._state_lock = Lock()
        self._closed = False
        self._close_incomplete = False
        self._sessions: WeakSet[TelemetryWriteSession] = WeakSet()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._writer_actor.call("initialize-schema", self._initialize_owned)

    def _connect_writer(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def _initialize_owned(self) -> None:
        with closing(self._connect_writer()) as db:
            initialize_telemetry_schema(db)

    def connect_reader(self) -> sqlite3.Connection:
        """Open a physically read-only observation connection."""
        uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
        db = sqlite3.connect(uri, uri=True, timeout=30)
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def writer_session(self) -> TelemetryWriteSession:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("telemetry backend closed")
            session = TelemetryWriteSession(self._connect_writer, self._writer_actor)
            self._sessions.add(session)
            return session

    def reader_session(self) -> TelemetryReadSession:
        return TelemetryReadSession(self.connect_reader)

    def insert_many(self, values: tuple[TelemetryStorageWriteRow, ...]) -> tuple[int, ...]:
        with self.writer_session() as session:
            return session.insert_many(values)

    def query(
        self,
        *,
        run_id: str,
        metric: str | None,
        decision_cycle_id: str | None,
        limit: int,
    ) -> tuple[TelemetryStorageReadRow, ...]:
        with self.reader_session() as session:
            return session.query(
                run_id=run_id,
                metric=metric,
                decision_cycle_id=decision_cycle_id,
                limit=limit,
            )

    def count(self) -> int:
        with self.reader_session() as session:
            return session.count()

    def close(self) -> None:
        errors: list[BaseException] = []
        with self._state_lock:
            if self._closed and not self._close_incomplete:
                return
            self._closed = True
            sessions = tuple(self._sessions)
            for session in sessions:
                try:
                    session.close()
                except BaseException as exc:
                    errors.append(exc)
            self._close_incomplete = bool(errors)
        if errors:
            raise ExceptionGroup("telemetry backend close failed", errors)

    def __enter__(self) -> "TelemetrySQLiteBackend":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()



__all__ = ["TelemetrySQLiteBackend", "TelemetryWriteSession", "TelemetryReadSession"]
