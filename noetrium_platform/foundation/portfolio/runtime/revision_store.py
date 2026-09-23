from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from threading import RLock

from noetrium_platform.foundation.kernel.kernel import require_sha256
from noetrium_platform.foundation.portfolio.api.revision import (
    PortfolioBranchRef,
    PortfolioRevision,
    PortfolioRevisionConflict,
    PortfolioRevisionNotFound,
    PortfolioTagRef,
)


def _require_target(
    revisions: dict[tuple[str, str], PortfolioRevision],
    subject_id: str,
    revision_digest: str,
) -> PortfolioRevision:
    try:
        return revisions[(subject_id, revision_digest)]
    except KeyError as exc:
        raise PortfolioRevisionNotFound(
            f"portfolio revision not found: {subject_id}@{revision_digest}"
        ) from exc


class InMemoryPortfolioRevisionStore:
    def __init__(self) -> None:
        self._revisions: dict[tuple[str, str], PortfolioRevision] = {}
        self._branches: dict[tuple[str, str], PortfolioBranchRef] = {}
        self._tags: dict[tuple[str, str], PortfolioTagRef] = {}
        self._lock = RLock()

    def commit(self, revision: PortfolioRevision) -> PortfolioRevision:
        if type(revision) is not PortfolioRevision:
            raise TypeError("portfolio commit requires PortfolioRevision")
        key = (revision.subject_id, revision.revision_digest)
        with self._lock:
            for parent in revision.parent_revision_digests:
                _require_target(self._revisions, revision.subject_id, parent)
            current = self._revisions.get(key)
            if current is not None:
                if current != revision:
                    raise PortfolioRevisionConflict("portfolio revision digest collision")
                return current
            self._revisions[key] = revision
            return revision

    def revision(self, subject_id: str, revision_digest: str) -> PortfolioRevision:
        require_sha256(revision_digest, "portfolio revision_digest")
        with self._lock:
            return _require_target(self._revisions, subject_id, revision_digest)

    def move_branch(
        self,
        subject_id: str,
        name: str,
        revision_digest: str,
        *,
        expected_revision_digest: str | None,
    ) -> PortfolioBranchRef:
        require_sha256(revision_digest, "portfolio branch revision_digest")
        if expected_revision_digest is not None:
            require_sha256(expected_revision_digest, "portfolio expected branch revision")
        with self._lock:
            _require_target(self._revisions, subject_id, revision_digest)
            key = (subject_id, name)
            current = self._branches.get(key)
            if current is None:
                if expected_revision_digest is not None:
                    raise PortfolioRevisionConflict("portfolio branch does not yet exist")
                result = PortfolioBranchRef(subject_id, name, revision_digest, 1)
                self._branches[key] = result
                return result
            if current.revision_digest != expected_revision_digest:
                raise PortfolioRevisionConflict(
                    "portfolio branch compare-and-swap revision mismatch"
                )
            if current.revision_digest == revision_digest:
                return current
            result = PortfolioBranchRef(
                subject_id,
                name,
                revision_digest,
                current.generation + 1,
            )
            self._branches[key] = result
            return result

    def branch(self, subject_id: str, name: str) -> PortfolioBranchRef:
        with self._lock:
            try:
                return self._branches[(subject_id, name)]
            except KeyError as exc:
                raise PortfolioRevisionNotFound(
                    f"portfolio branch not found: {subject_id}:{name}"
                ) from exc

    def tag(
        self,
        subject_id: str,
        name: str,
        revision_digest: str,
    ) -> PortfolioTagRef:
        require_sha256(revision_digest, "portfolio tag revision_digest")
        with self._lock:
            _require_target(self._revisions, subject_id, revision_digest)
            key = (subject_id, name)
            current = self._tags.get(key)
            candidate = PortfolioTagRef(subject_id, name, revision_digest)
            if current is not None:
                if current != candidate:
                    raise PortfolioRevisionConflict("portfolio tag is immutable")
                return current
            self._tags[key] = candidate
            return candidate

    def resolve_tag(self, subject_id: str, name: str) -> PortfolioTagRef:
        with self._lock:
            try:
                return self._tags[(subject_id, name)]
            except KeyError as exc:
                raise PortfolioRevisionNotFound(
                    f"portfolio tag not found: {subject_id}:{name}"
                ) from exc


class SQLitePortfolioRevisionStore:
    """Crash-durable Git-like revision/ref metadata authority."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("portfolio revision SQLite timeout must be positive")
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = float(timeout_seconds)
        with self._connection() as conn:
            self._ensure_schema(conn)

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.path, timeout=self.timeout_seconds, isolation_level=None)
        try:
            conn.execute(f"PRAGMA busy_timeout={max(1, int(self.timeout_seconds * 1000))}")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS portfolio_revision_meta("
            "key TEXT PRIMARY KEY,value TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS portfolio_revisions("
            "subject_id TEXT NOT NULL,revision_digest TEXT NOT NULL,"
            "payload_digest TEXT NOT NULL,payload_size_bytes INTEGER NOT NULL,"
            "parents_json TEXT NOT NULL,message TEXT NOT NULL,"
            "PRIMARY KEY(subject_id,revision_digest))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS portfolio_branches("
            "subject_id TEXT NOT NULL,name TEXT NOT NULL,revision_digest TEXT NOT NULL,"
            "generation INTEGER NOT NULL,PRIMARY KEY(subject_id,name))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS portfolio_tags("
            "subject_id TEXT NOT NULL,name TEXT NOT NULL,revision_digest TEXT NOT NULL,"
            "PRIMARY KEY(subject_id,name))"
        )
        conn.execute(
            "INSERT OR IGNORE INTO portfolio_revision_meta(key,value) "
            "VALUES('schema_version',?)",
            (str(self.SCHEMA_VERSION),),
        )
        row = conn.execute(
            "SELECT value FROM portfolio_revision_meta WHERE key='schema_version'"
        ).fetchone()
        if row is None or int(row[0]) != self.SCHEMA_VERSION:
            raise RuntimeError("unsupported SQLitePortfolioRevisionStore schema")

    @staticmethod
    def _decode_revision(row: tuple[object, ...]) -> PortfolioRevision:
        parents_raw = json.loads(str(row[4]))
        if not isinstance(parents_raw, list) or any(
            type(value) is not str for value in parents_raw
        ):
            raise RuntimeError("portfolio revision parents are corrupt")
        revision = PortfolioRevision(
            str(row[0]),
            str(row[2]),
            int(row[3]),
            tuple(parents_raw),
            str(row[5]),
        )
        if revision.revision_digest != str(row[1]):
            raise RuntimeError("portfolio revision digest integrity failure")
        return revision

    @staticmethod
    def _parents_json(parents: tuple[str, ...]) -> str:
        return json.dumps(parents, ensure_ascii=False, separators=(",", ":"))

    def _revision_tx(
        self,
        conn: sqlite3.Connection,
        subject_id: str,
        revision_digest: str,
    ) -> PortfolioRevision:
        row = conn.execute(
            "SELECT subject_id,revision_digest,payload_digest,payload_size_bytes,parents_json,message "
            "FROM portfolio_revisions WHERE subject_id=? AND revision_digest=?",
            (subject_id, revision_digest),
        ).fetchone()
        if row is None:
            raise PortfolioRevisionNotFound(
                f"portfolio revision not found: {subject_id}@{revision_digest}"
            )
        return self._decode_revision(row)

    def commit(self, revision: PortfolioRevision) -> PortfolioRevision:
        if type(revision) is not PortfolioRevision:
            raise TypeError("portfolio commit requires PortfolioRevision")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for parent in revision.parent_revision_digests:
                    self._revision_tx(conn, revision.subject_id, parent)
                row = conn.execute(
                    "SELECT subject_id,revision_digest,payload_digest,payload_size_bytes,parents_json,message "
                    "FROM portfolio_revisions WHERE subject_id=? AND revision_digest=?",
                    (revision.subject_id, revision.revision_digest),
                ).fetchone()
                if row is not None:
                    current = self._decode_revision(row)
                    if current != revision:
                        raise PortfolioRevisionConflict("portfolio revision digest collision")
                    conn.commit()
                    return current
                conn.execute(
                    "INSERT INTO portfolio_revisions("
                    "subject_id,revision_digest,payload_digest,payload_size_bytes,parents_json,message"
                    ") VALUES(?,?,?,?,?,?)",
                    (
                        revision.subject_id,
                        revision.revision_digest,
                        revision.payload_digest,
                        revision.payload_size_bytes,
                        self._parents_json(revision.parent_revision_digests),
                        revision.message,
                    ),
                )
                conn.commit()
                return revision
            except BaseException:
                if conn.in_transaction:
                    conn.rollback()
                raise

    def revision(self, subject_id: str, revision_digest: str) -> PortfolioRevision:
        require_sha256(revision_digest, "portfolio revision_digest")
        with self._connection() as conn:
            return self._revision_tx(conn, subject_id, revision_digest)

    def move_branch(
        self,
        subject_id: str,
        name: str,
        revision_digest: str,
        *,
        expected_revision_digest: str | None,
    ) -> PortfolioBranchRef:
        require_sha256(revision_digest, "portfolio branch revision_digest")
        if expected_revision_digest is not None:
            require_sha256(expected_revision_digest, "portfolio expected branch revision")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._revision_tx(conn, subject_id, revision_digest)
                row = conn.execute(
                    "SELECT revision_digest,generation FROM portfolio_branches "
                    "WHERE subject_id=? AND name=?",
                    (subject_id, name),
                ).fetchone()
                if row is None:
                    if expected_revision_digest is not None:
                        raise PortfolioRevisionConflict("portfolio branch does not yet exist")
                    result = PortfolioBranchRef(subject_id, name, revision_digest, 1)
                    conn.execute(
                        "INSERT INTO portfolio_branches("
                        "subject_id,name,revision_digest,generation) VALUES(?,?,?,?)",
                        (subject_id, name, revision_digest, 1),
                    )
                else:
                    current_digest = str(row[0])
                    generation = int(row[1])
                    if current_digest != expected_revision_digest:
                        raise PortfolioRevisionConflict(
                            "portfolio branch compare-and-swap revision mismatch"
                        )
                    if current_digest == revision_digest:
                        conn.commit()
                        return PortfolioBranchRef(
                            subject_id, name, current_digest, generation
                        )
                    result = PortfolioBranchRef(
                        subject_id, name, revision_digest, generation + 1
                    )
                    updated = conn.execute(
                        "UPDATE portfolio_branches SET revision_digest=?,generation=? "
                        "WHERE subject_id=? AND name=? AND revision_digest=? AND generation=?",
                        (
                            revision_digest,
                            generation + 1,
                            subject_id,
                            name,
                            current_digest,
                            generation,
                        ),
                    )
                    if updated.rowcount != 1:
                        raise PortfolioRevisionConflict(
                            "portfolio branch compare-and-swap lost authority"
                        )
                conn.commit()
                return result
            except BaseException:
                if conn.in_transaction:
                    conn.rollback()
                raise

    def branch(self, subject_id: str, name: str) -> PortfolioBranchRef:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT revision_digest,generation FROM portfolio_branches "
                "WHERE subject_id=? AND name=?",
                (subject_id, name),
            ).fetchone()
        if row is None:
            raise PortfolioRevisionNotFound(
                f"portfolio branch not found: {subject_id}:{name}"
            )
        return PortfolioBranchRef(subject_id, name, str(row[0]), int(row[1]))

    def tag(
        self,
        subject_id: str,
        name: str,
        revision_digest: str,
    ) -> PortfolioTagRef:
        require_sha256(revision_digest, "portfolio tag revision_digest")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._revision_tx(conn, subject_id, revision_digest)
                row = conn.execute(
                    "SELECT revision_digest FROM portfolio_tags "
                    "WHERE subject_id=? AND name=?",
                    (subject_id, name),
                ).fetchone()
                candidate = PortfolioTagRef(subject_id, name, revision_digest)
                if row is not None:
                    current = PortfolioTagRef(subject_id, name, str(row[0]))
                    if current != candidate:
                        raise PortfolioRevisionConflict("portfolio tag is immutable")
                    conn.commit()
                    return current
                conn.execute(
                    "INSERT INTO portfolio_tags(subject_id,name,revision_digest) VALUES(?,?,?)",
                    (subject_id, name, revision_digest),
                )
                conn.commit()
                return candidate
            except BaseException:
                if conn.in_transaction:
                    conn.rollback()
                raise

    def resolve_tag(self, subject_id: str, name: str) -> PortfolioTagRef:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT revision_digest FROM portfolio_tags "
                "WHERE subject_id=? AND name=?",
                (subject_id, name),
            ).fetchone()
        if row is None:
            raise PortfolioRevisionNotFound(
                f"portfolio tag not found: {subject_id}:{name}"
            )
        return PortfolioTagRef(subject_id, name, str(row[0]))


__all__ = [
    "InMemoryPortfolioRevisionStore",
    "SQLitePortfolioRevisionStore",
]
