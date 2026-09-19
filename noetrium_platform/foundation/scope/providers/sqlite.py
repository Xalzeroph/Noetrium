from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3

from noetrium_platform.foundation.kernel.kernel.logical_path import logical_absolute_path
from noetrium_platform.foundation.kernel.kernel.retry import retry_until_deadline
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind, ScopeLink
from noetrium_platform.foundation.scope.runtime import ScopeNotRegistered, ScopeRegistryConflict


class SQLiteScopeRegistry:
    """Crash-durable, process-safe authority for the immutable scope hierarchy."""

    SCHEMA_VERSION = 1
    PARENT_INDEX = "idx_scopes_parent_key"

    def __init__(self, path: str | Path, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("scope SQLite timeout must be positive")
        # Freeze one logical database authority at construction.  Reinterpreting
        # a relative path after a process cwd change would silently select a new DB.
        self.path = logical_absolute_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = float(timeout_seconds)
        with self._connection() as conn:
            self._ensure_schema(conn)
            conn.execute(
                "INSERT OR IGNORE INTO scopes(scope_key,kind,scope_id,parent_key) VALUES(?,?,?,NULL)",
                (PLATFORM_SCOPE.key, PLATFORM_SCOPE.kind.value, PLATFORM_SCOPE.scope_id),
            )

    @staticmethod
    def _is_lock_contention(exc: BaseException) -> bool:
        if not isinstance(exc, sqlite3.OperationalError):
            return False
        message = str(exc).lower()
        return "locked" in message or "busy" in message

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.path, timeout=self.timeout_seconds, isolation_level=None)
        try:
            conn.execute(f"PRAGMA busy_timeout={max(1, int(self.timeout_seconds * 1000))}")
            current_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            if current_mode != "wal":
                retry_until_deadline(
                    lambda: conn.execute("PRAGMA journal_mode=WAL"),
                    should_retry=self._is_lock_contention,
                    timeout_seconds=self.timeout_seconds,
                )
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE IF NOT EXISTS scope_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scopes(
                scope_key TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                parent_key TEXT REFERENCES scopes(scope_key),
                UNIQUE(kind, scope_id)
            )
            """
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self.PARENT_INDEX} ON scopes(parent_key)"
        )
        # Bootstrap is idempotent across concurrent first-open processes.
        # A competing creator may publish the version between our table creation
        # and metadata read, so use a conflict-safe insert and then validate the
        # single durable value that actually won.
        conn.execute(
            "INSERT OR IGNORE INTO scope_meta(key,value) VALUES('schema_version',?)",
            (str(self.SCHEMA_VERSION),),
        )
        row = conn.execute("SELECT value FROM scope_meta WHERE key='schema_version'").fetchone()
        if row is None:
            raise RuntimeError("SQLiteScopeRegistry schema version bootstrap failed")
        try:
            version = int(row[0])
        except (TypeError, ValueError) as exc:
            raise RuntimeError("invalid SQLiteScopeRegistry schema version") from exc
        if version != self.SCHEMA_VERSION:
            raise RuntimeError("unsupported SQLiteScopeRegistry schema")

    @staticmethod
    def _validate_parent(scope: ScopeIdentity, parent: ScopeIdentity | None) -> None:
        if scope.kind is ScopeKind.PLATFORM:
            if scope != PLATFORM_SCOPE or parent is not None:
                raise ScopeRegistryConflict("platform scope has one fixed root identity")
            return
        if parent is None:
            raise ScopeRegistryConflict("non-platform scope requires explicit parent")
        try:
            ScopeLink(scope, parent)
        except ValueError as exc:
            raise ScopeRegistryConflict(str(exc)) from exc

    @staticmethod
    def _decode(row: tuple[object, ...]) -> tuple[ScopeIdentity, ScopeIdentity | None]:
        scope = ScopeIdentity(ScopeKind(str(row[1])), str(row[2]))
        parent_key = row[3]
        if parent_key is None:
            if scope != PLATFORM_SCOPE:
                raise ScopeRegistryConflict(f"non-platform scope has no parent: {scope.key}")
            return scope, None
        parent_kind, parent_id = str(parent_key).split(":", 1)
        parent = ScopeIdentity(ScopeKind(parent_kind), parent_id)
        SQLiteScopeRegistry._validate_parent(scope, parent)
        return scope, parent

    def register(self, scope: ScopeIdentity, parent: ScopeIdentity | None) -> None:
        self._validate_parent(scope, parent)
        with self._connection() as conn:
            retry_until_deadline(
                lambda: conn.execute("BEGIN IMMEDIATE"),
                should_retry=self._is_lock_contention,
                timeout_seconds=self.timeout_seconds,
            )
            try:
                if parent is not None:
                    parent_row = conn.execute(
                        "SELECT 1 FROM scopes WHERE scope_key=?", (parent.key,)
                    ).fetchone()
                    if parent_row is None:
                        raise ScopeNotRegistered(parent.key)
                row = conn.execute(
                    "SELECT kind,scope_id,parent_key FROM scopes WHERE scope_key=?",
                    (scope.key,),
                ).fetchone()
                parent_key = None if parent is None else parent.key
                if row is not None:
                    if row[2] != parent_key:
                        raise ScopeRegistryConflict(f"scope parent already fixed: {scope.key}")
                    conn.commit()
                    return
                conn.execute(
                    "INSERT INTO scopes(scope_key,kind,scope_id,parent_key) VALUES(?,?,?,?)",
                    (scope.key, scope.kind.value, scope.scope_id, parent_key),
                )
                conn.commit()
            except BaseException:
                if conn.in_transaction:
                    conn.rollback()
                raise

    def parent(self, scope: ScopeIdentity) -> ScopeIdentity | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT kind,scope_id,parent_key FROM scopes WHERE scope_key=?",
                (scope.key,),
            ).fetchone()
        if row is None:
            raise ScopeNotRegistered(scope.key)
        return self._decode((scope.key, *row))[1]

    def ancestry(self, scope: ScopeIdentity) -> tuple[ScopeIdentity, ...]:
        """Resolve leaf-to-root ancestry from one consistent SQLite statement."""

        with self._connection() as conn:
            rows = conn.execute(
                """
                WITH RECURSIVE ancestry(
                    scope_key, kind, scope_id, parent_key, depth, path, cycle
                ) AS (
                    SELECT scope_key, kind, scope_id, parent_key, 0,
                           '|' || scope_key || '|', 0
                    FROM scopes WHERE scope_key=?
                    UNION ALL
                    SELECT s.scope_key, s.kind, s.scope_id, s.parent_key, a.depth + 1,
                           a.path || s.scope_key || '|',
                           CASE WHEN instr(a.path, '|' || s.scope_key || '|') > 0 THEN 1 ELSE 0 END
                    FROM scopes AS s
                    JOIN ancestry AS a ON s.scope_key = a.parent_key
                    WHERE a.cycle = 0
                )
                SELECT scope_key, kind, scope_id, parent_key, depth, cycle
                FROM ancestry
                ORDER BY depth ASC
                """,
                (scope.key,),
            ).fetchall()
        if not rows:
            raise ScopeNotRegistered(scope.key)
        if any(int(row[5]) for row in rows):
            repeated = next(str(row[0]) for row in rows if int(row[5]))
            raise ScopeRegistryConflict(f"scope cycle detected at {repeated}")
        last_parent = rows[-1][3]
        if last_parent is not None:
            raise ScopeNotRegistered(str(last_parent))
        identities = tuple(
            ScopeIdentity(ScopeKind(str(row[1])), str(row[2])) for row in rows
        )
        if identities[-1] != PLATFORM_SCOPE:
            raise ScopeRegistryConflict("scope ancestry does not terminate at platform root")
        for child, parent in zip(identities, identities[1:]):
            self._validate_parent(child, parent)
        return identities

    def children(self, scope: ScopeIdentity) -> tuple[ScopeIdentity, ...]:
        with self._connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM scopes WHERE scope_key=?", (scope.key,)
            ).fetchone()
            if exists is None:
                raise ScopeNotRegistered(scope.key)
            rows = conn.execute(
                "SELECT kind,scope_id FROM scopes WHERE parent_key=? ORDER BY kind,scope_id",
                (scope.key,),
            ).fetchall()
        return tuple(ScopeIdentity(ScopeKind(str(row[0])), str(row[1])) for row in rows)

    def contains(self, scope: ScopeIdentity) -> bool:
        with self._connection() as conn:
            return conn.execute(
                "SELECT 1 FROM scopes WHERE scope_key=?", (scope.key,)
            ).fetchone() is not None


__all__ = ["SQLiteScopeRegistry"]
