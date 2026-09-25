from __future__ import annotations

import sqlite3
from threading import Lock
from typing import Callable

from noetrium_platform.evidence.observability.telemetry.metric.api import (
    TelemetryStorageWriteRow,
    TelemetryWriteActorPort,
)


INSERT_SQL = """INSERT INTO metric_observations(
metric,value,timestamp,run_id,study_id,condition_id,task_id,decision_cycle_id,
trace_id,span_id,operation_id,component_id,participant_generations_json,
dimensions_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


class TelemetryWriteSession:
    """Actor-owned persistent SQLite writer session.

    The sqlite connection is created, used, committed and closed only on the
    serial actor owner thread.  The caller-side lifecycle lock spans each actor
    RPC so insert and close are linearizable for one session; SQLite work still
    executes only on the injected serial actor owner thread.
    """

    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection],
        writer_actor: TelemetryWriteActorPort,
    ) -> None:
        self._connect = connect
        self._actor = writer_actor
        self._state_lock = Lock()
        self._closed = False
        self._db: sqlite3.Connection | None = None

    def _insert_many_owned(self, values: tuple[TelemetryStorageWriteRow, ...]) -> tuple[int, ...]:
        if self._db is None:
            self._db = self._connect()
        with self._db:
            self._db.executemany(INSERT_SQL, values)
            end = int(self._db.execute("SELECT last_insert_rowid()").fetchone()[0])
            start = end - len(values) + 1
        return tuple(range(start, end + 1))

    def insert_many(self, values: tuple[TelemetryStorageWriteRow, ...]) -> tuple[int, ...]:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("telemetry write session closed")
            if not values:
                return ()
            return self._actor.call("insert-many", self._insert_many_owned, values)

    def _close_owned(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._actor.call("close-session", self._close_owned)
            self._closed = True

    def __enter__(self) -> "TelemetryWriteSession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
