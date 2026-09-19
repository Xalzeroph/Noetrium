from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactNotFound,
    ArtifactQuery,
    ArtifactRecord,
    ArtifactRegistryConflict,
    ArtifactRegistryCorruptionError,
    ArtifactRetention,
)
from noetrium_platform.foundation.kernel.kernel import (
    strict_finite_json_digest as canonical_digest,
    strict_finite_json_text,
    strict_json_loads,
)
from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.evidence.artifact._sqlite_connection import connect_artifact_reader, connect_artifact_writer, rollback_artifact_writer
from noetrium_platform.evidence.artifact._sqlite_types import require_optional_text, require_text
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind


class SQLiteArtifactRegistry:
    """Immutable SQLite artifact catalog with record-integrity verification."""

    _COLUMNS = (
        "artifact_id", "kind", "scope_kind", "scope_id", "digest",
        "producer_component_id", "producer_operation_id", "media_type", "lineage_json",
        "declared_retention", "metadata_json", "record_sha256",
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
            CREATE TABLE IF NOT EXISTS artifacts(
                artifact_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                scope_kind TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                digest TEXT NOT NULL,
                producer_component_id TEXT NOT NULL,
                producer_operation_id TEXT,
                media_type TEXT NOT NULL,
                lineage_json TEXT NOT NULL,
                declared_retention TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_scope ON artifacts(scope_kind,scope_id,artifact_id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_kind ON artifacts(kind,artifact_id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_producer ON artifacts(producer_component_id,artifact_id);
            """
        )
        columns = tuple(row[1] for row in db.execute("PRAGMA table_info(artifacts)"))
        if columns != cls._COLUMNS:
            raise ArtifactRegistryCorruptionError(
                f"unsupported artifact catalog schema columns: {columns!r}"
            )

    @staticmethod
    def _document(record: ArtifactRecord) -> dict[str, object]:
        return {
            "artifact_id": record.artifact_id,
            "kind": record.kind.value,
            "scope": {"kind": record.scope.kind.value, "scope_id": record.scope.scope_id},
            "digest": record.digest,
            "producer_component_id": record.producer_component_id,
            "producer_operation_id": record.producer_operation_id,
            "media_type": record.media_type,
            "lineage": tuple(
                {"artifact_id": ref.artifact_id, "content_sha256": ref.content_sha256}
                for ref in record.lineage
            ),
            "retention": record.retention.value,
            "metadata": record.metadata,
        }

    @classmethod
    def _record_digest(cls, record: ArtifactRecord) -> str:
        return canonical_digest(cls._document(record))

    @classmethod
    def _encode(cls, record: ArtifactRecord) -> tuple[object, ...]:
        return (
            record.artifact_id,
            record.kind.value,
            record.scope.kind.value,
            record.scope.scope_id,
            record.digest,
            record.producer_component_id,
            record.producer_operation_id,
            record.media_type,
            strict_finite_json_text(tuple(
                {"artifact_id": ref.artifact_id, "content_sha256": ref.content_sha256}
                for ref in record.lineage
            )),
            record.retention.value,
            json.dumps(record.metadata, ensure_ascii=False, separators=(",", ":")),
            cls._record_digest(record),
        )

    @classmethod
    def _decode(cls, row: tuple[object, ...]) -> ArtifactRecord:
        try:
            lineage = strict_json_loads(require_text(row[8], label="artifact lineage_json"))
            metadata = json.loads(require_text(row[10], label="artifact metadata_json"))
            if not isinstance(lineage, list) or not isinstance(metadata, list):
                raise TypeError("artifact collection fields have invalid JSON shape")
            lineage_items: list[ArtifactContentIdentity] = []
            for value in lineage:
                if not isinstance(value, dict) or set(value) != {"artifact_id", "content_sha256"}:
                    raise TypeError("artifact lineage JSON must contain exact content-identity objects")
                artifact_id = value.get("artifact_id")
                content_sha256 = value.get("content_sha256")
                if not isinstance(artifact_id, str) or not isinstance(content_sha256, str):
                    raise TypeError("artifact lineage content identity fields must be strings")
                lineage_items.append(ArtifactContentIdentity(artifact_id, content_sha256))
            if any(
                not isinstance(pair, list)
                or len(pair) != 2
                or not isinstance(pair[0], str)
                or not isinstance(pair[1], str)
                for pair in metadata
            ):
                raise TypeError("artifact metadata JSON must contain string pairs")
            record = ArtifactRecord(
                artifact_id=require_text(row[0], label="artifact_id"),
                kind=ArtifactKind(require_text(row[1], label="artifact kind")),
                scope=ScopeIdentity(
                    ScopeKind(require_text(row[2], label="artifact scope_kind")),
                    require_text(row[3], label="artifact scope_id"),
                ),
                digest=require_text(row[4], label="artifact digest"),
                producer_component_id=require_text(
                    row[5], label="artifact producer_component_id"
                ),
                producer_operation_id=require_optional_text(
                    row[6], label="artifact producer_operation_id"
                ),
                media_type=require_text(row[7], label="artifact media_type"),
                lineage=tuple(lineage_items),
                retention=ArtifactRetention(
                    require_text(row[9], label="artifact retention")
                ),
                metadata=tuple((pair[0], pair[1]) for pair in metadata),
            )
            stored_digest = require_text(row[11], label="artifact record_sha256")
        except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ArtifactRegistryCorruptionError("artifact catalog record cannot be decoded") from exc
        if cls._record_digest(record) != stored_digest:
            raise ArtifactRegistryCorruptionError(
                f"artifact catalog record integrity mismatch: {record.artifact_id}"
            )
        return record

    @classmethod
    def _select_columns(cls) -> str:
        return ",".join(cls._COLUMNS)

    def put(self, artifact: ArtifactRecord) -> ArtifactRecord:
        encoded = self._encode(artifact)
        with closing(self._connect_writer()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                current_row = db.execute(
                    f"SELECT {self._select_columns()} FROM artifacts WHERE artifact_id=?",
                    (artifact.artifact_id,),
                ).fetchone()
                if current_row is not None:
                    current = self._decode(current_row)
                    if current != artifact:
                        raise ArtifactRegistryConflict(artifact.artifact_id)
                    db.execute("COMMIT")
                    return current
                db.execute(
                    "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    encoded,
                )
                db.execute("COMMIT")
            except BaseException as primary:
                rollback_artifact_writer(db, primary)
                raise
        return artifact

    def get(self, artifact_id: str) -> ArtifactRecord:
        with closing(self._connect_reader()) as db:
            row = db.execute(
                f"SELECT {self._select_columns()} FROM artifacts WHERE artifact_id=?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise ArtifactNotFound(artifact_id)
        return self._decode(row)

    def query(self, query: ArtifactQuery = ArtifactQuery()) -> tuple[ArtifactRecord, ...]:
        clauses: list[str] = []
        args: list[object] = []
        if query.scope is not None:
            clauses.extend(("scope_kind=?", "scope_id=?"))
            args.extend((query.scope.kind.value, query.scope.scope_id))
        if query.kind is not None:
            clauses.append("kind=?")
            args.append(query.kind.value)
        if query.producer_component_id is not None:
            clauses.append("producer_component_id=?")
            args.append(query.producer_component_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        args.append(query.limit)
        with closing(self._connect_reader()) as db:
            rows = db.execute(
                f"SELECT {self._select_columns()} FROM artifacts{where} ORDER BY artifact_id LIMIT ?",
                args,
            ).fetchall()
        return tuple(self._decode(row) for row in rows)


__all__ = ["SQLiteArtifactRegistry"]
