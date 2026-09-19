from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from noetrium_platform.evidence.artifact.reference.api import (
    ArtifactReference,
    ArtifactReferenceConflict,
    ArtifactReferenceCorruptionError,
    ArtifactReferenceNotFound,
)
from noetrium_platform.foundation.kernel.kernel import strict_finite_json_digest as canonical_digest
from noetrium_platform.evidence.artifact._sqlite_connection import connect_artifact_reader, connect_artifact_writer, rollback_artifact_writer
from noetrium_platform.evidence.artifact._sqlite_types import require_integer, require_text
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind


class SQLiteArtifactReferenceStore:
    """Scope-local CAS alias authority with row-integrity verification."""

    _COLUMNS = (
        "reference_id", "scope_kind", "scope_id", "artifact_id", "generation", "record_sha256",
    )

    def __init__(self, path: str | Path, *, timeout_seconds: float = 30.0) -> None:
        self.path = Path(path).expanduser().resolve()
        self.timeout_seconds = timeout_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect_writer()) as db:
            self._ensure_schema(db)

    def _connect_writer(self) -> sqlite3.Connection:
        return connect_artifact_writer(self.path, timeout_seconds=self.timeout_seconds)

    def _connect_reader(self) -> sqlite3.Connection:
        return connect_artifact_reader(self.path, timeout_seconds=self.timeout_seconds)

    @classmethod
    def _ensure_schema(cls, db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS artifact_references(
                reference_id TEXT NOT NULL,
                scope_kind TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                generation INTEGER NOT NULL CHECK(generation > 0),
                record_sha256 TEXT NOT NULL,
                PRIMARY KEY(scope_kind,scope_id,reference_id)
            ) WITHOUT ROWID;
            CREATE INDEX IF NOT EXISTS idx_artifact_references_artifact
                ON artifact_references(artifact_id,scope_kind,scope_id,reference_id);
            """
        )
        try:
            schema_rows = tuple(db.execute("PRAGMA table_info(artifact_references)"))
            columns = tuple(
                require_text(row[1], label="artifact reference schema column name")
                for row in schema_rows
            )
            pk = tuple(
                name for _, name in sorted(
                    (
                        require_integer(row[5], label="artifact reference schema pk order", minimum=1),
                        require_text(row[1], label="artifact reference schema pk column"),
                    )
                    for row in schema_rows
                    if require_integer(row[5], label="artifact reference schema pk order") > 0
                )
            )
        except (IndexError, TypeError, ValueError) as exc:
            raise ArtifactReferenceCorruptionError(
                "artifact reference schema metadata cannot be decoded"
            ) from exc
        if columns != cls._COLUMNS:
            raise ArtifactReferenceCorruptionError(
                f"unsupported artifact reference schema columns: {columns!r}"
            )
        if pk != ("scope_kind", "scope_id", "reference_id"):
            raise ArtifactReferenceCorruptionError(
                f"artifact reference primary key does not bind scope identity: {pk!r}"
            )

    @staticmethod
    def _document(reference: ArtifactReference) -> dict[str, object]:
        return {
            "reference_id": reference.reference_id,
            "scope": {"kind": reference.scope.kind.value, "scope_id": reference.scope.scope_id},
            "artifact_id": reference.artifact_id,
            "generation": reference.generation,
        }

    @classmethod
    def _record_digest(cls, reference: ArtifactReference) -> str:
        return canonical_digest(cls._document(reference))

    @classmethod
    def _encode(cls, reference: ArtifactReference) -> tuple[object, ...]:
        return (
            reference.reference_id,
            reference.scope.kind.value,
            reference.scope.scope_id,
            reference.artifact_id,
            reference.generation,
            cls._record_digest(reference),
        )

    @classmethod
    def _decode(cls, row: tuple[object, ...]) -> ArtifactReference:
        try:
            reference = ArtifactReference(
                reference_id=require_text(row[0], label="artifact reference_id"),
                scope=ScopeIdentity(
                    ScopeKind(require_text(row[1], label="artifact reference scope_kind")),
                    require_text(row[2], label="artifact reference scope_id"),
                ),
                artifact_id=require_text(row[3], label="artifact reference artifact_id"),
                generation=require_integer(
                    row[4], label="artifact reference generation", minimum=1
                ),
            )
            stored_digest = require_text(row[5], label="artifact reference record_sha256")
        except (IndexError, TypeError, ValueError) as exc:
            raise ArtifactReferenceCorruptionError("stored artifact reference cannot be decoded") from exc
        if cls._record_digest(reference) != stored_digest:
            raise ArtifactReferenceCorruptionError(
                f"artifact reference integrity mismatch: {reference.reference_id}"
            )
        return reference

    @classmethod
    def _select(
        cls,
        db: sqlite3.Connection,
        reference_id: str,
        scope: ScopeIdentity,
    ) -> tuple[object, ...] | None:
        return db.execute(
            f"SELECT {','.join(cls._COLUMNS)} FROM artifact_references "
            "WHERE scope_kind=? AND scope_id=? AND reference_id=?",
            (scope.kind.value, scope.scope_id, reference_id),
        ).fetchone()

    def resolve(self, reference_id: str, scope: ScopeIdentity) -> ArtifactReference:
        if not reference_id.strip():
            raise ValueError("artifact reference_id must be non-empty")
        with closing(self._connect_reader()) as db:
            row = self._select(db, reference_id, scope)
        if row is None:
            raise ArtifactReferenceNotFound(reference_id)
        return self._decode(row)

    def compare_and_set(
        self,
        reference_id: str,
        scope: ScopeIdentity,
        *,
        expected_generation: int,
        artifact_id: str,
    ) -> ArtifactReference:
        if (
            not reference_id.strip()
            or not artifact_id.strip()
            or isinstance(expected_generation, bool)
            or expected_generation < 0
        ):
            raise ValueError("artifact reference CAS inputs are invalid")
        with closing(self._connect_writer()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = self._select(db, reference_id, scope)
                if row is None:
                    if expected_generation != 0:
                        raise ArtifactReferenceConflict(
                            f"missing reference {reference_id!r}; expected generation {expected_generation}"
                        )
                    created = ArtifactReference(reference_id, scope, artifact_id, 1)
                    db.execute(
                        "INSERT INTO artifact_references VALUES(?,?,?,?,?,?)",
                        self._encode(created),
                    )
                    db.execute("COMMIT")
                    return created
                current = self._decode(row)
                if current.generation != expected_generation:
                    raise ArtifactReferenceConflict(
                        f"reference generation conflict: expected {expected_generation}, actual {current.generation}"
                    )
                if current.artifact_id == artifact_id:
                    db.execute("COMMIT")
                    return current
                updated = ArtifactReference(reference_id, scope, artifact_id, current.generation + 1)
                db.execute(
                    "UPDATE artifact_references SET artifact_id=?,generation=?,record_sha256=? "
                    "WHERE scope_kind=? AND scope_id=? AND reference_id=?",
                    (
                        updated.artifact_id,
                        updated.generation,
                        self._record_digest(updated),
                        scope.kind.value,
                        scope.scope_id,
                        reference_id,
                    ),
                )
                db.execute("COMMIT")
                return updated
            except BaseException as primary:
                rollback_artifact_writer(db, primary)
                raise


__all__ = ["SQLiteArtifactReferenceStore"]
