from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
import math
from pathlib import Path
import sqlite3

from .persistence import EffectJournalPersistenceBackend, EncodedEffectIntentRecord


_COLUMNS = "intent_id,intent_json,intent_digest,request_digest,run_id,lifetime_id,phase,effect_json,effect_digest,consumption_json,consumption_digest"
_TABLE = "effect_intents"
_META_TABLE = "effect_journal_meta"


def _decode(row: tuple[object, ...]) -> EncodedEffectIntentRecord:
    return EncodedEffectIntentRecord(
        str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]),
        None if row[5] is None else str(row[5]), str(row[6]),
        None if row[7] is None else str(row[7]), None if row[8] is None else str(row[8]),
        None if row[9] is None else str(row[9]), None if row[10] is None else str(row[10]),
    )


class SQLiteEffectJournalWriteSession(AbstractContextManager["SQLiteEffectJournalWriteSession"]):
    def __init__(self, backend: "SQLiteEffectJournalBackend") -> None:
        self.backend = backend
        self.conn = backend.connect()
        try:
            self.conn.execute("BEGIN IMMEDIATE")
        except BaseException:
            self.conn.close()
            raise
        self._committed = False

    def read(self, intent_id: str) -> EncodedEffectIntentRecord | None:
        row = self.conn.execute(
            f"SELECT {_COLUMNS} FROM {_TABLE} WHERE intent_id=?", (intent_id,)
        ).fetchone()
        return _decode(row) if row is not None else None

    def insert(self, value: EncodedEffectIntentRecord) -> bool:
        cursor = self.conn.execute(
            f"INSERT OR IGNORE INTO {_TABLE}({_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (value.intent_id, value.intent_json, value.intent_digest, value.request_digest,
             value.run_id, value.lifetime_id, value.phase, value.effect_json, value.effect_digest,
             value.consumption_json, value.consumption_digest),
        )
        return cursor.rowcount == 1

    def update(
        self,
        value: EncodedEffectIntentRecord,
        *,
        expected_phase: str,
        expected_effect_digest: str | None,
    ) -> bool:
        cursor = self.conn.execute(
            f"""
            UPDATE {_TABLE}
            SET intent_json=?,intent_digest=?,request_digest=?,run_id=?,lifetime_id=?,phase=?,effect_json=?,effect_digest=?,consumption_json=?,consumption_digest=?
            WHERE intent_id=? AND phase=? AND effect_digest IS ?
            """,
            (value.intent_json, value.intent_digest, value.request_digest, value.run_id, value.lifetime_id,
             value.phase, value.effect_json, value.effect_digest, value.consumption_json, value.consumption_digest,
             value.intent_id, expected_phase, expected_effect_digest),
        )
        return cursor.rowcount == 1

    def commit(self) -> None:
        self.conn.commit()
        self._committed = True

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is not None or not self._committed:
                self.conn.rollback()
        finally:
            self.conn.close()
        return False


class SQLiteEffectJournalBackend(EffectJournalPersistenceBackend):
    """SQLite persistence for generic effect intents.

    """

    durability = "crash_durable"
    SCHEMA_VERSION = 2

    def __init__(self, path: Path, *, timeout_seconds: float = 30.0) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
            raise ValueError("effect journal timeout_seconds must be finite and positive")
        self.timeout_seconds = float(timeout_seconds)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=self.timeout_seconds, isolation_level=None)
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def connection(self):
        """Own and close each backend connection, including read-only uses."""

        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")
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
                        consumption_json TEXT,
                        consumption_digest TEXT
                    )
                    """
                )
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS effect_intents_scope_phase_idx "
                    f"ON {_TABLE}(run_id,lifetime_id,phase,intent_id)"
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
                    if current_version != self.SCHEMA_VERSION:
                        raise RuntimeError("unsupported SQLiteEffectIntentJournal schema")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def read(self, intent_id: str) -> EncodedEffectIntentRecord | None:
        with self.connection() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM {_TABLE} WHERE intent_id=?", (intent_id,)
            ).fetchone()
        return _decode(row) if row is not None else None

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
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM {_TABLE} "
                f"WHERE run_id=? AND lifetime_id IS ? AND phase IN ({placeholders})"
                f"{exclusion} ORDER BY intent_id",
                params,
            ).fetchall()
        return tuple(_decode(row) for row in rows)

    def write_session(self) -> SQLiteEffectJournalWriteSession:
        return SQLiteEffectJournalWriteSession(self)


__all__ = ["SQLiteEffectJournalBackend", "SQLiteEffectJournalWriteSession"]
