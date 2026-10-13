from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactNotFound,
    ArtifactQuery,
    ArtifactDescriptor,
    ArtifactRegistryConflict,
    ArtifactRegistryCorruptionError,
    ArtifactRetention,
)
from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    strict_finite_json_text,
    strict_json_loads,
)
from noetrium_platform.evidence.artifact.contracts import ArtifactContentIdentity
from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    DurableSQLiteReaderOwner,
    DurableSQLiteWriterOwner,
    immediate_sqlite_transaction,
    sqlite_read_snapshot,
)
from noetrium_platform.evidence.artifact._sqlite_types import require_optional_text, require_text
from noetrium_platform.foundation.governance.api import (
    NoetriumUnit,
    scope_from_data,
    scope_id,
    scope_kind,
    scope_to_data,
)


class SQLiteArtifactRegistry:
    """Immutable SQLite artifact catalog with carrier-independent integrity."""

    STORE_SCHEMA_VERSION = 2
    INTEGRITY_SCHEMA = "artifact.catalog.descriptor-integrity.v1"

    @classmethod
    def default_path(
        cls,
        root: str | Path,
        filename: str = "artifact-catalog.sqlite3",
    ) -> Path:
        path = Path(filename)
        return Path(root) / (
            f"{path.stem}.v{cls.STORE_SCHEMA_VERSION}{path.suffix}"
        )

    _COLUMNS = (
        "artifact_id", "kind", "scope_kind", "scope_id", "digest",
        "producer_component_id", "producer_operation_id", "media_type", "lineage_json",
        "declared_retention", "metadata_json", "record_digest",
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
        self._readers = DurableSQLiteReaderOwner(
            self.path, timeout_seconds=self.timeout_seconds,
        )

    @property
    def writer_connection_open_count(self) -> int:
        return self._writers.open_count

    def close(self) -> None:
        self._readers.close()
        self._writers.close()

    @classmethod
    def _ensure_schema(cls, db: sqlite3.Connection) -> None:
        artifacts_exist = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='artifacts'"
        ).fetchone() is not None
        db.execute(
            "CREATE TABLE IF NOT EXISTS artifact_registry_meta("
            "key TEXT PRIMARY KEY,value TEXT NOT NULL)"
        )
        existing_version = db.execute(
            "SELECT value FROM artifact_registry_meta WHERE key='schema_version'"
        ).fetchone()
        if artifacts_exist and existing_version is None:
            raise ArtifactRegistryCorruptionError(
                "unversioned artifact registry is not valid for current authority"
            )
        if (
            existing_version is not None
            and int(existing_version[0]) != cls.STORE_SCHEMA_VERSION
        ):
            raise ArtifactRegistryCorruptionError(
                "unsupported artifact registry schema generation"
            )
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
                record_digest TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_scope ON artifacts(scope_kind,scope_id,artifact_id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_kind ON artifacts(kind,artifact_id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_digest ON artifacts(digest,artifact_id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_producer ON artifacts(producer_component_id,artifact_id);
            """
        )
        columns = tuple(row[1] for row in db.execute("PRAGMA table_info(artifacts)"))
        if columns != cls._COLUMNS:
            raise ArtifactRegistryCorruptionError(
                f"unsupported artifact catalog schema columns: {columns!r}"
            )
        if existing_version is None:
            db.execute(
                "INSERT INTO artifact_registry_meta(key,value) VALUES('schema_version',?)",
                (str(cls.STORE_SCHEMA_VERSION),),
            )

    @staticmethod
    def _document(record: ArtifactDescriptor) -> dict[str, object]:
        return {
            "artifact_id": record.artifact_id,
            "kind": record.kind.value,
            "scope": scope_to_data(record.scope),
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
    def _record_digest(cls, descriptor: ArtifactDescriptor) -> str:
        return canonical_digest(
            {
                "schema": cls.INTEGRITY_SCHEMA,
                "descriptor": cls._document(descriptor),
            }
        )

    @classmethod
    def _encode(cls, record: ArtifactDescriptor) -> tuple[object, ...]:
        return (
            record.artifact_id,
            record.kind.value,
            scope_kind(record.scope).value,
            scope_id(record.scope),
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
    def _descriptor_from_row(cls, row: tuple[object, ...]) -> ArtifactDescriptor:
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
            return ArtifactDescriptor(
                artifact_id=require_text(row[0], label="artifact_id"),
                kind=ArtifactKind(require_text(row[1], label="artifact kind")),
                scope=scope_from_data(
                    {
                        "kind": require_text(row[2], label="artifact scope_kind"),
                        "scope_id": require_text(row[3], label="artifact scope_id"),
                    }
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
        except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ArtifactRegistryCorruptionError("artifact catalog record cannot be decoded") from exc

    @classmethod
    def _decode(cls, row: tuple[object, ...]) -> ArtifactDescriptor:
        record = cls._descriptor_from_row(row)
        try:
            stored_digest = require_text(row[11], label="artifact record_digest")
        except (IndexError, TypeError, ValueError) as exc:
            raise ArtifactRegistryCorruptionError("artifact catalog record cannot be decoded") from exc
        if cls._record_digest(record) != stored_digest:
            raise ArtifactRegistryCorruptionError(
                f"artifact catalog record integrity mismatch: {record.artifact_id}"
            )
        return record

    @classmethod
    def _select_columns(cls) -> str:
        return ",".join(cls._COLUMNS)

    def put_many(
        self,
        artifacts: tuple[ArtifactDescriptor, ...],
    ) -> tuple[ArtifactDescriptor, ...]:
        if type(artifacts) is not tuple or any(
            type(artifact) is not ArtifactDescriptor for artifact in artifacts
        ):
            raise TypeError("artifact catalog put_many requires ArtifactDescriptor tuple")
        if not artifacts:
            return ()
        ids = tuple(artifact.artifact_id for artifact in artifacts)
        if len(ids) != len(set(ids)):
            raise ValueError("artifact catalog put_many contains duplicate artifact ids")
        results: list[ArtifactDescriptor] = []
        with self._writers.session() as db:
            with immediate_sqlite_transaction(
                db,
                timeout_seconds=self.timeout_seconds,
                label="artifact catalog",
            ):
                for artifact in artifacts:
                    current_row = db.execute(
                        f"SELECT {self._select_columns()} FROM artifacts WHERE artifact_id=?",
                        (artifact.artifact_id,),
                    ).fetchone()
                    if current_row is not None:
                        current = self._decode(current_row)
                        if current != artifact:
                            raise ArtifactRegistryConflict(artifact.artifact_id)
                        results.append(current)
                        continue
                    db.execute(
                        "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        self._encode(artifact),
                    )
                    results.append(artifact)
        return tuple(results)

    def put(self, artifact: ArtifactDescriptor) -> ArtifactDescriptor:
        return self.put_many((artifact,))[0]

    def get(self, artifact_id: str) -> ArtifactDescriptor:
        with self._readers.session() as db, sqlite_read_snapshot(db):
            row = db.execute(
                f"SELECT {self._select_columns()} FROM artifacts WHERE artifact_id=?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise ArtifactNotFound(artifact_id)
        return self._decode(row)

    def query(self, query: ArtifactQuery = ArtifactQuery()) -> tuple[ArtifactDescriptor, ...]:
        clauses: list[str] = []
        args: list[object] = []
        if query.scope is not None:
            clauses.extend(("scope_kind=?", "scope_id=?"))
            args.extend((scope_kind(query.scope).value, scope_id(query.scope)))
        if query.kind is not None:
            clauses.append("kind=?")
            args.append(query.kind.value)
        if query.producer_component_id is not None:
            clauses.append("producer_component_id=?")
            args.append(query.producer_component_id)
        if query.digest is not None:
            clauses.append("digest=?")
            args.append(query.digest)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        args.append(query.limit)
        with self._readers.session() as db, sqlite_read_snapshot(db):
            rows = db.execute(
                f"SELECT {self._select_columns()} FROM artifacts{where} ORDER BY artifact_id LIMIT ?",
                args,
            ).fetchall()
        return tuple(self._decode(row) for row in rows)


__all__ = ["SQLiteArtifactRegistry"]
