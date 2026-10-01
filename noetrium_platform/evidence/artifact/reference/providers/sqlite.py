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
from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    DurableSQLiteWriterOwner,
    immediate_sqlite_transaction,
    open_durable_sqlite_reader,
)
from noetrium_platform.evidence.artifact._sqlite_types import require_integer, require_text
from noetrium_platform.foundation.governance.api import ScopeIdentity, ScopeKind


class SQLiteArtifactReferenceStore:
    """Scope-local CAS alias authority with row-integrity verification."""

    _COLUMNS = (
        "reference_id", "scope_kind", "scope_id", "artifact_id", "generation", "record_sha256",
    )

    def __init__(self, path: str | Path, *, timeout_seconds: float = 30.0) -> None:
        self.path = Path(path).expanduser().resolve()
        self.timeout_seconds = timeout_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._writers = DurableSQLiteWriterOwner(
            self.path,
            timeout_seconds=self.timeout_seconds,
        )
        with self._writers.session() as db:
            self._ensure_schema(db)

    @property
    def writer_connection_open_count(self) -> int:
        return self._writers.open_count

    def close(self) -> None:
        self._writers.close()

    def _connect_reader(self) -> sqlite3.Connection:
        return open_durable_sqlite_reader(self.path, timeout_seconds=self.timeout_seconds)

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

    def resolve_many(
        self,
        keys: tuple[tuple[str, ScopeIdentity], ...],
    ) -> tuple[ArtifactReference | None, ...]:
        if type(keys) is not tuple:
            raise TypeError("artifact reference resolve_many keys must be tuple")
        if not keys:
            return ()
        for key in keys:
            if (
                type(key) is not tuple
                or len(key) != 2
                or type(key[0]) is not str
                or not key[0].strip()
                or type(key[1]) is not ScopeIdentity
            ):
                raise TypeError(
                    "artifact reference resolve_many keys must be "
                    "(reference_id, ScopeIdentity) pairs"
                )
        rows: list[ArtifactReference | None] = []
        with closing(self._connect_reader()) as db:
            for reference_id, scope in keys:
                row = self._select(db, reference_id, scope)
                rows.append(None if row is None else self._decode(row))
        return tuple(rows)

    def resolve(self, reference_id: str, scope: ScopeIdentity) -> ArtifactReference:
        current = self.resolve_many(((reference_id, scope),))[0]
        if current is None:
            raise ArtifactReferenceNotFound(reference_id)
        return current

    def compare_and_set_many(
        self,
        mutations: tuple[tuple[str, ScopeIdentity, int, str], ...],
    ) -> tuple[ArtifactReference, ...]:
        if type(mutations) is not tuple:
            raise TypeError("artifact reference CAS batch must be tuple")
        if not mutations:
            return ()
        keys: list[tuple[str, str, str]] = []
        for mutation in mutations:
            if type(mutation) is not tuple or len(mutation) != 4:
                raise TypeError("artifact reference CAS batch mutation must be 4-tuple")
            reference_id, scope, expected_generation, artifact_id = mutation
            if (
                type(reference_id) is not str
                or not reference_id.strip()
                or type(scope) is not ScopeIdentity
                or type(artifact_id) is not str
                or not artifact_id.strip()
                or isinstance(expected_generation, bool)
                or type(expected_generation) is not int
                or expected_generation < 0
            ):
                raise ValueError("artifact reference CAS inputs are invalid")
            keys.append((scope.kind.value, scope.scope_id, reference_id))
        if len(keys) != len(set(keys)):
            raise ValueError("artifact reference CAS batch contains duplicate references")

        results: list[ArtifactReference] = []
        with self._writers.session() as db:
            with immediate_sqlite_transaction(
                db,
                timeout_seconds=self.timeout_seconds,
                label="artifact reference",
            ):
                for reference_id, scope, expected_generation, artifact_id in mutations:
                    row = self._select(db, reference_id, scope)
                    if row is None:
                        if expected_generation != 0:
                            raise ArtifactReferenceConflict(
                                f"missing reference {reference_id!r}; "
                                f"expected generation {expected_generation}"
                            )
                        created = ArtifactReference(reference_id, scope, artifact_id, 1)
                        db.execute(
                            "INSERT INTO artifact_references VALUES(?,?,?,?,?,?)",
                            self._encode(created),
                        )
                        results.append(created)
                        continue
                    current = self._decode(row)
                    if current.generation != expected_generation:
                        raise ArtifactReferenceConflict(
                            "reference generation conflict: "
                            f"expected {expected_generation}, actual {current.generation}"
                        )
                    if current.artifact_id == artifact_id:
                        results.append(current)
                        continue
                    updated = ArtifactReference(
                        reference_id, scope, artifact_id, current.generation + 1
                    )
                    db.execute(
                        "UPDATE artifact_references "
                        "SET artifact_id=?,generation=?,record_sha256=? "
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
                    results.append(updated)
        return tuple(results)

    def compare_and_set(
        self,
        reference_id: str,
        scope: ScopeIdentity,
        *,
        expected_generation: int,
        artifact_id: str,
    ) -> ArtifactReference:
        return self.compare_and_set_many(
            ((reference_id, scope, expected_generation, artifact_id),)
        )[0]


__all__ = ["SQLiteArtifactReferenceStore"]
