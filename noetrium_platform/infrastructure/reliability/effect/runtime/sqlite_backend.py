from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
import math
from pathlib import Path

from noetrium_platform.foundation.kernel.event import event_field, is_event_unit
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.unit_codec import decode_unit, encode_unit
from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    abort_sqlite_writer,
    DurableSQLiteReaderOwner,
    DurableSQLiteWriterOwner,
    sqlite_read_snapshot,
    begin_immediate_sqlite_transaction,
    rollback_sqlite_writer,
)

from .persistence import EffectJournalPersistenceBackend, EncodedEffectIntentRecord


_COLUMNS = "intent_id,intent_json,intent_digest,request_digest,run_id,lifetime_id,phase,effect_json,effect_digest,result_snapshot_json,consumption_json,consumption_digest"
_TABLE = "effect_intents"
_EVENT_TABLE = "effect_events"
_META_TABLE = "effect_journal_meta"


def _decode(row: tuple[object, ...]) -> EncodedEffectIntentRecord:
    return EncodedEffectIntentRecord(
        str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]),
        None if row[5] is None else str(row[5]), str(row[6]),
        None if row[7] is None else str(row[7]), None if row[8] is None else str(row[8]),
        None if row[9] is None else str(row[9]), None if row[10] is None else str(row[10]),
        None if row[11] is None else str(row[11]),
    )


class SQLiteEffectJournalWriteSession(AbstractContextManager["SQLiteEffectJournalWriteSession"]):
    def __init__(self, backend: "SQLiteEffectJournalBackend") -> None:
        self.backend = backend
        self._connection_session = backend.connection()
        self.conn = self._connection_session.__enter__()
        try:
            begin_immediate_sqlite_transaction(
                self.conn,
                timeout_seconds=backend.timeout_seconds,
            )
        except BaseException as exc:
            self._connection_session.__exit__(
                type(exc),
                exc,
                exc.__traceback__,
            )
            raise
        self._committed = False

    def read(self, intent_id: str) -> EncodedEffectIntentRecord | None:
        row = self.conn.execute(
            f"SELECT {_COLUMNS} FROM {_TABLE} WHERE intent_id=?", (intent_id,)
        ).fetchone()
        return _decode(row) if row is not None else None

    def read_event_head(self, intent_id: str) -> NoetriumUnit | None:
        row = self.conn.execute(
            f"SELECT current_event_digest FROM {_TABLE} WHERE intent_id=?",
            (intent_id,),
        ).fetchone()
        if row is None:
            return None
        if row[0] is None:
            raise RuntimeError(
                "effect projection exists without causal event head: " + intent_id
            )
        event_row = self.conn.execute(
            f"SELECT payload FROM {_EVENT_TABLE} WHERE event_digest=?",
            (str(row[0]),),
        ).fetchone()
        if event_row is None:
            raise RuntimeError(
                "effect projection event head is missing: " + intent_id
            )
        event = decode_unit(bytes(event_row[0]))
        if event.unit_digest != str(row[0]) or not is_event_unit(event):
            raise RuntimeError("effect causal event head is invalid: " + intent_id)
        return event

    def scan_scope_phases(
        self,
        *,
        run_id: str,
        lifetime_id: str | None,
        phases: tuple[str, ...],
        exclude_intent_id: str | None = None,
    ) -> tuple[EncodedEffectIntentRecord, ...]:
        if not phases:
            return ()
        placeholders = ",".join("?" for _ in phases)
        exclusion = "" if exclude_intent_id is None else " AND intent_id<>?"
        params: tuple[object, ...] = (run_id, lifetime_id, *phases)
        if exclude_intent_id is not None:
            params += (exclude_intent_id,)
        rows = self.conn.execute(
            f"SELECT {_COLUMNS} FROM {_TABLE} "
            f"WHERE run_id=? AND lifetime_id IS ? AND phase IN ({placeholders})"
            f"{exclusion} ORDER BY intent_id",
            params,
        ).fetchall()
        return tuple(_decode(row) for row in rows)

    def insert(
        self,
        value: EncodedEffectIntentRecord,
        *,
        event: NoetriumUnit,
    ) -> bool:
        if not is_event_unit(event):
            raise TypeError("effect journal append requires system.event Unit")
        domain = str(event_field(event, "authority_domain"))
        event_cursor = self.conn.execute(
            f"INSERT OR IGNORE INTO {_EVENT_TABLE}"
            "(event_digest,intent_id,run_id,authority_domain,payload) "
            "VALUES(?,?,?,?,?)",
            (
                event.unit_digest,
                value.intent_id,
                value.run_id,
                domain,
                encode_unit(event),
            ),
        )
        if event_cursor.rowcount != 1:
            return False
        cursor = self.conn.execute(
            f"INSERT OR IGNORE INTO {_TABLE}({_COLUMNS},current_event_digest) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                value.intent_id,
                value.intent_json,
                value.intent_digest,
                value.request_digest,
                value.run_id,
                value.lifetime_id,
                value.phase,
                value.effect_json,
                value.effect_digest,
                value.result_snapshot_json,
                value.consumption_json,
                value.consumption_digest,
                event.unit_digest,
            ),
        )
        return cursor.rowcount == 1

    def update(
        self,
        value: EncodedEffectIntentRecord,
        *,
        event: NoetriumUnit,
        expected_event_digest: str,
        expected_phase: str,
        expected_effect_digest: str | None,
    ) -> bool:
        if not is_event_unit(event):
            raise TypeError("effect journal append requires system.event Unit")
        domain = str(event_field(event, "authority_domain"))
        event_cursor = self.conn.execute(
            f"INSERT OR IGNORE INTO {_EVENT_TABLE}"
            "(event_digest,intent_id,run_id,authority_domain,payload) "
            "VALUES(?,?,?,?,?)",
            (
                event.unit_digest,
                value.intent_id,
                value.run_id,
                domain,
                encode_unit(event),
            ),
        )
        if event_cursor.rowcount != 1:
            return False
        cursor = self.conn.execute(
            f"""
            UPDATE {_TABLE}
            SET intent_json=?,intent_digest=?,request_digest=?,run_id=?,
                lifetime_id=?,phase=?,effect_json=?,effect_digest=?,
                result_snapshot_json=?,consumption_json=?,consumption_digest=?,
                current_event_digest=?
            WHERE intent_id=? AND current_event_digest=?
              AND phase=? AND effect_digest IS ?
            """,
            (
                value.intent_json,
                value.intent_digest,
                value.request_digest,
                value.run_id,
                value.lifetime_id,
                value.phase,
                value.effect_json,
                value.effect_digest,
                value.result_snapshot_json,
                value.consumption_json,
                value.consumption_digest,
                event.unit_digest,
                value.intent_id,
                expected_event_digest,
                expected_phase,
                expected_effect_digest,
            ),
        )
        return cursor.rowcount == 1

    def commit(self) -> None:
        self.conn.commit()
        self._committed = True

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is not None or not self._committed:
                if isinstance(exc, BaseException):
                    rollback_sqlite_writer(
                        self.conn,
                        exc,
                        label="effect",
                    )
                else:
                    abort_sqlite_writer(self.conn)
        finally:
            self._connection_session.__exit__(exc_type, exc, tb)
        return False


class SQLiteEffectJournalBackend(EffectJournalPersistenceBackend):
    """SQLite persistence for generic effect intents.

    """

    durability = "crash_durable"
    SCHEMA_VERSION = 4

    def __init__(self, path: Path, *, timeout_seconds: float = 30.0) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
            raise ValueError("effect journal timeout_seconds must be finite and positive")
        self.timeout_seconds = float(timeout_seconds)
        self._connections = DurableSQLiteWriterOwner(
            self.path,
            timeout_seconds=self.timeout_seconds,
        )
        self._initialize()
        # Effect intent and causal event-head reads never borrow the physical
        # effect writer permit. In-write reconciliation uses WriteSession's
        # own transaction-consistent read methods, never this outer view.
        self._readers = DurableSQLiteReaderOwner(
            self.path, timeout_seconds=self.timeout_seconds,
        )

    @property
    def connection_open_count(self) -> int:
        return self._connections.open_count

    @contextmanager
    def connection(self):
        """Borrow the process-owned durable writer session."""

        with self._connections.session() as conn:
            yield conn

    def close(self) -> None:
        self._readers.close()
        self._connections.close()

    def _initialize(self) -> None:
        with self.connection() as conn:
            begin_immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
            )
            try:
                conn.execute(f"CREATE TABLE IF NOT EXISTS {_META_TABLE} (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_TABLE} (
                        intent_id TEXT PRIMARY KEY,
                        intent_json TEXT NOT NULL,
                        intent_digest TEXT NOT NULL,
                        request_digest TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        lifetime_id TEXT,
                        phase TEXT NOT NULL,
                        effect_json TEXT,
                        effect_digest TEXT,
                        result_snapshot_json TEXT,
                        consumption_json TEXT,
                        consumption_digest TEXT,
                        current_event_digest TEXT
                    )
                    """
                )
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS effect_intents_scope_phase_idx "
                    f"ON {_TABLE}(run_id,lifetime_id,phase,intent_id)"
                )
                conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_EVENT_TABLE} (
                        event_digest TEXT PRIMARY KEY,
                        intent_id TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        authority_domain TEXT NOT NULL,
                        payload BLOB NOT NULL
                    )
                    """
                )
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS effect_events_intent_idx "
                    f"ON {_EVENT_TABLE}(intent_id,event_digest)"
                )
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS effect_events_run_idx "
                    f"ON {_EVENT_TABLE}(run_id,event_digest)"
                )
                row = conn.execute(
                    f"SELECT value FROM {_META_TABLE} WHERE key='schema_version'"
                ).fetchone()
                if row is None:
                    conn.execute(
                        f"INSERT INTO {_META_TABLE}(key,value) VALUES('schema_version',?)",
                        (str(self.SCHEMA_VERSION),),
                    )
                else:
                    current_version = int(row[0])
                    if current_version == 2:
                        columns = {
                            str(info[1])
                            for info in conn.execute(f"PRAGMA table_info({_TABLE})")
                        }
                        if "result_snapshot_json" not in columns:
                            conn.execute(
                                f"ALTER TABLE {_TABLE} ADD COLUMN result_snapshot_json TEXT"
                            )
                        current_version = 3
                    if current_version == 3:
                        columns = {
                            str(info[1])
                            for info in conn.execute(f"PRAGMA table_info({_TABLE})")
                        }
                        if "current_event_digest" not in columns:
                            conn.execute(
                                f"ALTER TABLE {_TABLE} ADD COLUMN current_event_digest TEXT"
                            )
                        current_version = 4
                    if current_version != self.SCHEMA_VERSION:
                        raise RuntimeError("unsupported sqlite_effect_intent_journal schema")
                    conn.execute(
                        f"UPDATE {_META_TABLE} SET value=? WHERE key='schema_version'",
                        (str(self.SCHEMA_VERSION),),
                    )
                conn.commit()
            except BaseException as primary:
                rollback_sqlite_writer(
                    conn,
                    primary,
                    label="effect",
                )
                raise

    def read(self, intent_id: str) -> EncodedEffectIntentRecord | None:
        with self._readers.session() as conn, sqlite_read_snapshot(conn):
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM {_TABLE} WHERE intent_id=?", (intent_id,)
            ).fetchone()
        return _decode(row) if row is not None else None

    def read_event_head(self, intent_id: str) -> NoetriumUnit | None:
        with self._readers.session() as conn, sqlite_read_snapshot(conn):
            row = conn.execute(
                f"SELECT current_event_digest FROM {_TABLE} WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
            if row is None:
                return None
            if row[0] is None:
                raise RuntimeError(
                    "effect projection exists without causal event head: " + intent_id
                )
            event_row = conn.execute(
                f"SELECT payload FROM {_EVENT_TABLE} WHERE event_digest=?",
                (str(row[0]),),
            ).fetchone()
        if event_row is None:
            raise RuntimeError(
                "effect projection event head is missing: " + intent_id
            )
        event = decode_unit(bytes(event_row[0]))
        if event.unit_digest != str(row[0]) or not is_event_unit(event):
            raise RuntimeError("effect causal event head is invalid: " + intent_id)
        return event

    def scan_scope_phases(
        self,
        *,
        run_id: str,
        lifetime_id: str | None,
        phases: tuple[str, ...],
        exclude_intent_id: str | None = None,
    ) -> tuple[EncodedEffectIntentRecord, ...]:
        if not phases:
            return ()
        placeholders = ",".join("?" for _ in phases)
        exclusion = "" if exclude_intent_id is None else " AND intent_id<>?"
        params: tuple[object, ...] = (run_id, lifetime_id, *phases)
        if exclude_intent_id is not None:
            params += (exclude_intent_id,)
        with self._readers.session() as conn, sqlite_read_snapshot(conn):
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM {_TABLE} "
                f"WHERE run_id=? AND lifetime_id IS ? AND phase IN ({placeholders})"
                f"{exclusion} ORDER BY intent_id",
                params,
            ).fetchall()
        return tuple(_decode(row) for row in rows)

    def scan_run(
        self,
        *,
        run_id: str,
    ) -> tuple[EncodedEffectIntentRecord, ...]:
        if type(run_id) is not str or not run_id.strip():
            raise ValueError("effect journal run_id must be non-empty text")
        with self._readers.session() as conn, sqlite_read_snapshot(conn):
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM {_TABLE} "
                "WHERE run_id=? ORDER BY intent_id",
                (run_id,),
            ).fetchall()
        return tuple(_decode(row) for row in rows)

    def scan_run_events(
        self,
        *,
        run_id: str,
    ) -> tuple[NoetriumUnit, ...]:
        if type(run_id) is not str or not run_id.strip():
            raise ValueError("effect event run_id must be non-empty text")
        with self._readers.session() as conn, sqlite_read_snapshot(conn):
            rows = conn.execute(
                f"SELECT payload FROM {_EVENT_TABLE} "
                "WHERE run_id=? ORDER BY event_digest",
                (run_id,),
            ).fetchall()
        events = tuple(decode_unit(bytes(row[0])) for row in rows)
        if any(not is_event_unit(event) for event in events):
            raise RuntimeError("effect event journal contains non-event Unit")
        return events

    def write_session(self) -> SQLiteEffectJournalWriteSession:
        return SQLiteEffectJournalWriteSession(self)


__all__ = ["SQLiteEffectJournalBackend", "SQLiteEffectJournalWriteSession"]
