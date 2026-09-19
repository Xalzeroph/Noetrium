from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from noetrium_platform.evidence.data._sqlite_types import require_blob, require_integer, require_text
from noetrium_platform.evidence.data._sqlite_transaction import rollback_data_writer
from noetrium_platform.evidence.data.state.api import StateBootstrapConflict, StateCorruptionError


@dataclass(frozen=True, slots=True)
class EncodedAggregate:
    aggregate_id: str
    version: int
    generation: str
    digest: str
    payload: bytes
    payload_sha256: str


class SQLiteStateWriteSession(AbstractContextManager["SQLiteStateWriteSession"]):
    def __init__(self, backend: "SQLiteStateBackend") -> None:
        self.backend = backend
        self.conn = backend.connect_writer()
        self.conn.execute("BEGIN IMMEDIATE")
        self._complete = False

    def read(self, aggregate_id: str) -> EncodedAggregate | None:
        row = self.conn.execute(
            "SELECT aggregate_id,version,generation,digest,payload,payload_sha256 "
            "FROM aggregates WHERE aggregate_id=?",
            (aggregate_id,),
        ).fetchone()
        return self.backend.decode_row(row) if row is not None else None

    def read_many(self, aggregate_ids: tuple[str, ...]) -> tuple[EncodedAggregate, ...]:
        """Read a request set without N/SQLite-variable-limit round trips.

        The common path uses one indexed ``IN`` query.  Extremely large request
        sets are materialized once into a connection-local TEMP relation and
        joined in one query, avoiding the previous Python chunk loop that made
        database round trips scale with request cardinality.
        """

        if not aggregate_ids:
            return ()
        variable_limit = max(1, self.conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER))
        if len(aggregate_ids) <= variable_limit:
            placeholders = ",".join(["?"] * len(aggregate_ids))
            found = self.conn.execute(
                "SELECT aggregate_id,version,generation,digest,payload,payload_sha256 "
                f"FROM aggregates WHERE aggregate_id IN ({placeholders})",
                aggregate_ids,
            ).fetchall()
            return tuple(self.backend.decode_row(row) for row in found)

        self.conn.execute(
            "CREATE TEMP TABLE IF NOT EXISTS state_read_many_ids("
            "aggregate_id TEXT PRIMARY KEY) WITHOUT ROWID"
        )
        self.conn.execute("DELETE FROM state_read_many_ids")
        self.conn.executemany(
            "INSERT INTO state_read_many_ids(aggregate_id) VALUES(?)",
            tuple((aggregate_id,) for aggregate_id in aggregate_ids),
        )
        found = self.conn.execute(
            "SELECT a.aggregate_id,a.version,a.generation,a.digest,a.payload,a.payload_sha256 "
            "FROM aggregates AS a "
            "JOIN state_read_many_ids AS requested USING(aggregate_id)"
        ).fetchall()
        return tuple(self.backend.decode_row(row) for row in found)

    def update(
        self,
        value: EncodedAggregate,
        *,
        expected_version: int,
        expected_generation: str,
    ) -> bool:
        cursor = self.conn.execute(
            """
            UPDATE aggregates
            SET version=?,generation=?,digest=?,payload=?,payload_sha256=?
            WHERE aggregate_id=? AND version=? AND generation=?
            """,
            (
                value.version,
                value.generation,
                value.digest,
                value.payload,
                value.payload_sha256,
                value.aggregate_id,
                expected_version,
                expected_generation,
            ),
        )
        return cursor.rowcount == 1

    def update_many(
        self,
        rows: tuple[tuple[EncodedAggregate, int, str], ...],
    ) -> bool:
        if not rows:
            return True
        cursor = self.conn.executemany(
            """
            UPDATE aggregates
            SET version=?,generation=?,digest=?,payload=?,payload_sha256=?
            WHERE aggregate_id=? AND version=? AND generation=?
            """,
            (
                (
                    value.version,
                    value.generation,
                    value.digest,
                    value.payload,
                    value.payload_sha256,
                    value.aggregate_id,
                    expected_version,
                    expected_generation,
                )
                for value, expected_version, expected_generation in rows
            ),
        )
        return cursor.rowcount == len(rows)

    def commit(self) -> None:
        self.conn.commit()
        self._complete = True

    def __exit__(self, exc_type, exc, tb) -> bool:
        del tb
        primary = exc if isinstance(exc, BaseException) else None
        try:
            if exc_type is not None or not self._complete:
                if primary is None:
                    try:
                        self.conn.rollback()
                    except BaseException as rollback_exc:
                        primary = rollback_exc
                        raise
                else:
                    rollback_data_writer(self.conn, primary)
        finally:
            try:
                self.conn.close()
            except BaseException as close_exc:
                if primary is None:
                    raise
                primary.add_note(
                    "data sqlite close failed: "
                    f"{type(close_exc).__name__}"
                )
        return False


class SQLiteStateBackend:
    """SQLite mechanics only; knows nothing about scientific payload schemas or CAS policy."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path, *, timeout_seconds: float = 30.0) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = timeout_seconds

    def connect_writer(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=self.timeout_seconds, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def connect_reader(self) -> sqlite3.Connection:
        uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=self.timeout_seconds, isolation_level=None)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def writer_connection(self):
        conn = self.connect_writer()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def reader_connection(self):
        conn = self.connect_reader()
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def decode_row(row: tuple[object, ...]) -> EncodedAggregate:
        try:
            return EncodedAggregate(
                require_text(row[0], label="state aggregate_id"),
                require_integer(row[1], label="state version", minimum=0),
                require_text(row[2], label="state generation"),
                require_text(row[3], label="state digest"),
                require_blob(row[4], label="state payload"),
                require_text(row[5], label="state payload_sha256"),
            )
        except (IndexError, TypeError, ValueError) as exc:
            raise StateCorruptionError("canonical state row cannot be decoded") from exc

    def initialize(self, initial: tuple[EncodedAggregate, ...]) -> None:
        with self.writer_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._ensure_schema(conn)
                for value in initial:
                    self._insert_if_absent(conn, value)
                conn.commit()
            except BaseException as primary:
                rollback_data_writer(conn, primary)
                raise

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE IF NOT EXISTS state_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aggregates (
                aggregate_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                generation TEXT NOT NULL,
                digest TEXT NOT NULL,
                payload BLOB NOT NULL,
                payload_sha256 TEXT NOT NULL
            )
            """
        )
        row = conn.execute("SELECT value FROM state_meta WHERE key='schema_version'").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO state_meta(key,value) VALUES('schema_version',?)",
                (str(self.SCHEMA_VERSION),),
            )
        else:
            try:
                schema_version = int(
                    require_text(row[0], label="canonical state schema_version")
                )
            except (TypeError, ValueError) as exc:
                raise StateCorruptionError("canonical state schema_version is corrupt") from exc
            if schema_version != self.SCHEMA_VERSION:
                raise StateCorruptionError(
                    f"unsupported SQLiteAtomicStateStore schema: {schema_version}"
                )

    @staticmethod
    def _insert_if_absent(conn: sqlite3.Connection, value: EncodedAggregate) -> None:
        cursor = conn.execute(
            """
            INSERT INTO aggregates(
                aggregate_id,version,generation,digest,payload,payload_sha256
            ) VALUES(?,?,?,?,?,?)
            ON CONFLICT(aggregate_id) DO NOTHING
            """,
            (
                value.aggregate_id,
                value.version,
                value.generation,
                value.digest,
                value.payload,
                value.payload_sha256,
            ),
        )
        if cursor.rowcount == 1:
            return
        row = conn.execute(
            "SELECT aggregate_id,version,generation,digest,payload,payload_sha256 "
            "FROM aggregates WHERE aggregate_id=?",
            (value.aggregate_id,),
        ).fetchone()
        if row is None:
            raise StateBootstrapConflict(
                f"canonical state bootstrap disappeared: {value.aggregate_id}"
            )
        current = SQLiteStateBackend.decode_row(row)
        if current != value:
            raise StateBootstrapConflict(
                f"canonical state conflicts with bootstrap value: {value.aggregate_id}"
            )

    def read(self, aggregate_id: str) -> EncodedAggregate | None:
        with self.reader_connection() as conn:
            row = conn.execute(
                "SELECT aggregate_id,version,generation,digest,payload,payload_sha256 "
                "FROM aggregates WHERE aggregate_id=?",
                (aggregate_id,),
            ).fetchone()
        return self.decode_row(row) if row is not None else None

    def write_session(self) -> SQLiteStateWriteSession:
        return SQLiteStateWriteSession(self)
