from __future__ import annotations

from threading import Lock

from noetrium_platform.evidence.observability.telemetry.metric.api import (
    TelemetryStorageWriteRow,
    TelemetryWriteActorPort,
)
from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    DurableSQLiteWriterOwner,
)


INSERT_SQL = """INSERT INTO metric_observations(
metric,value,timestamp,run_id,study_id,condition_id,task_id,decision_cycle_id,
trace_id,span_id,operation_id,component_id,participant_generations_json,
dimensions_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


class TelemetryWriteSession:
    """Logical telemetry writer session over the backend-owned SQLite writer.

    All mutation is serialized through the injected actor. The physical SQLite
    writer belongs to the backend-level DurableSQLiteWriterOwner, so independent
    logical sessions share one durability configuration and one persistent writer
    without acquiring a second storage authority.
    """

    def __init__(
        self,
        writers: DurableSQLiteWriterOwner,
        writer_actor: TelemetryWriteActorPort,
    ) -> None:
        self._writers = writers
        self._actor = writer_actor
        self._state_lock = Lock()
        self._closed = False

    def _insert_many_owned(self, values: tuple[TelemetryStorageWriteRow, ...]) -> tuple[int, ...]:
        with self._writers.session() as db:
            with db:
                db.executemany(INSERT_SQL, values)
                end = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
                start = end - len(values) + 1
        return tuple(range(start, end + 1))

    def insert_many(self, values: tuple[TelemetryStorageWriteRow, ...]) -> tuple[int, ...]:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("telemetry write session closed")
            if not values:
                return ()
            return self._actor.call("insert-many", self._insert_many_owned, values)

    @staticmethod
    def _close_owned() -> None:
        return None

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
