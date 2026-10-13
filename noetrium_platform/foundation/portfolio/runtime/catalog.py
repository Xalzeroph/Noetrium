from __future__ import annotations

from pathlib import Path
import sqlite3
from threading import RLock

from noetrium_platform.foundation.api import PLATFORM_SCOPE, ScopeIndexPort
from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    durable_sqlite_connection,
    immediate_sqlite_transaction,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.portfolio.api.unit_semantics import (
    decode_project_manifest_bytes,
    encode_project_manifest,
    project_manifest_program_id,
    project_manifest_project_id,
    project_manifest_scope,
    project_manifest_version,
    require_project_manifest,
)


class PortfolioConflict(RuntimeError):
    pass


class PortfolioNotFound(KeyError):
    pass


class InMemoryPortfolioCatalog:
    """Disposable project-manifest Unit index with no parallel hierarchy truth."""

    def __init__(self, scopes: ScopeIndexPort) -> None:
        self._scopes = scopes
        self._projects: dict[str, NoetriumUnit] = {}
        self._lock = RLock()

    def register_project(self, manifest: NoetriumUnit) -> None:
        manifest = require_project_manifest(manifest)
        project_id = project_manifest_project_id(manifest)
        with self._lock:
            current = self._projects.get(project_id)
            if current is not None and current != manifest:
                raise PortfolioConflict(
                    f"identity already registered with different content: {project_id}"
                )
            self._scopes.register(project_manifest_scope(manifest), PLATFORM_SCOPE)
            self._projects[project_id] = manifest

    def project(self, project_id: str) -> NoetriumUnit:
        with self._lock:
            try:
                return self._projects[project_id]
            except KeyError as exc:
                raise PortfolioNotFound(project_id) from exc

    def projects(
        self,
        *,
        program_id: str | None = None,
    ) -> tuple[NoetriumUnit, ...]:
        with self._lock:
            rows = tuple(self._projects.values())
        if program_id is not None:
            rows = tuple(
                row for row in rows if project_manifest_program_id(row) == program_id
            )
        return tuple(sorted(rows, key=project_manifest_project_id))


class SQLitePortfolioCatalog:
    """Crash-durable exact Unit index for project manifests."""

    SCHEMA_VERSION = 2

    def __init__(
        self,
        path: str | Path,
        scopes: ScopeIndexPort,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("portfolio SQLite timeout must be positive")
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._scopes = scopes
        self.timeout_seconds = float(timeout_seconds)
        with self._connection() as conn:
            self._ensure_schema(conn)
        self.rebuild_scope_index()

    def _connection(self):
        return durable_sqlite_connection(
            self.path,
            timeout_seconds=self.timeout_seconds,
        )

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE portfolio_meta("
            "key TEXT PRIMARY KEY,value TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE projects("
            "project_id TEXT PRIMARY KEY,"
            "version TEXT NOT NULL,"
            "program_id TEXT NOT NULL,"
            "manifest BLOB NOT NULL)"
        )
        conn.execute(
            "INSERT INTO portfolio_meta(key,value) VALUES('schema_version',?)",
            (str(self.SCHEMA_VERSION),),
        )

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        meta_exists = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='portfolio_meta'"
        ).fetchone() is not None
        projects_exists = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='projects'"
        ).fetchone() is not None

        version: int | None = None
        if meta_exists:
            row = conn.execute(
                "SELECT value FROM portfolio_meta WHERE key='schema_version'"
            ).fetchone()
            if row is not None:
                try:
                    version = int(row[0])
                except (TypeError, ValueError):
                    version = None

        if (
            meta_exists
            and projects_exists
            and version == self.SCHEMA_VERSION
        ):
            return

        # This database is a rebuildable projection of immutable project-manifest
        # Units.  A retired schema therefore has no migration path and owns no
        # truth worth preserving: replace it atomically with the current index.
        with immediate_sqlite_transaction(
            conn,
            timeout_seconds=self.timeout_seconds,
            label="portfolio catalog schema projection",
        ):
            conn.execute("DROP TABLE IF EXISTS projects")
            conn.execute("DROP TABLE IF EXISTS portfolio_meta")
            self._create_schema(conn)

    def _insert(self, statement: str, values: tuple[object, ...]) -> None:
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="portfolio catalog",
            ):
                conn.execute(statement, values)

    def rebuild_scope_index(self) -> None:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT manifest FROM projects ORDER BY project_id"
            ).fetchall()
        for (raw,) in rows:
            manifest = decode_project_manifest_bytes(bytes(raw))
            self._scopes.register(project_manifest_scope(manifest), PLATFORM_SCOPE)

    def register_project(self, manifest: NoetriumUnit) -> None:
        manifest = require_project_manifest(manifest)
        project_id = project_manifest_project_id(manifest)
        raw = encode_project_manifest(manifest)
        self._scopes.register(project_manifest_scope(manifest), PLATFORM_SCOPE)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT manifest FROM projects WHERE project_id=?",
                (project_id,),
            ).fetchone()
        if row is not None:
            if bytes(row[0]) != raw:
                raise PortfolioConflict(
                    f"identity already registered with different content: {project_id}"
                )
            return
        self._insert(
            "INSERT OR IGNORE INTO projects("
            "project_id,version,program_id,manifest) VALUES(?,?,?,?)",
            (
                project_id,
                project_manifest_version(manifest),
                project_manifest_program_id(manifest),
                raw,
            ),
        )
        if self.project(project_id) != manifest:
            raise PortfolioConflict(
                f"identity already registered with different content: {project_id}"
            )

    def project(self, project_id: str) -> NoetriumUnit:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT manifest FROM projects WHERE project_id=?",
                (project_id,),
            ).fetchone()
        if row is None:
            raise PortfolioNotFound(project_id)
        return decode_project_manifest_bytes(bytes(row[0]))

    def projects(
        self,
        *,
        program_id: str | None = None,
    ) -> tuple[NoetriumUnit, ...]:
        query = "SELECT manifest FROM projects"
        values: tuple[object, ...] = ()
        if program_id is not None:
            query += " WHERE program_id=?"
            values = (program_id,)
        with self._connection() as conn:
            rows = conn.execute(
                query + " ORDER BY project_id",
                values,
            ).fetchall()
        return tuple(
            decode_project_manifest_bytes(bytes(row[0]))
            for row in rows
        )


__all__ = [
    "InMemoryPortfolioCatalog",
    "PortfolioConflict",
    "PortfolioNotFound",
    "SQLitePortfolioCatalog",
]
