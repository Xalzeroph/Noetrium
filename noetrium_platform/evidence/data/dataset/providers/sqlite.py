from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from noetrium_platform.evidence.data.dataset.api import (
    DatasetIdentity,
    DatasetNotFound,
    DatasetQuery,
    DatasetRegistryConflict,
    DatasetRegistryCorruptionError,
    DatasetVersion,
)
from noetrium_platform.evidence.data._canonical import DataCanonicalDecodingError, canonical_digest, strict_json_loads
from noetrium_platform.evidence.data._sqlite_transaction import rollback_data_writer
from noetrium_platform.evidence.data._sqlite_types import require_optional_text, require_text
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind


class SQLiteDatasetRegistry:
    """Immutable portable dataset-version registry; physical placement is external."""

    _COLUMNS = (
        "dataset_key", "dataset_id", "version", "scope_kind", "scope_id",
        "content_sha256", "schema_ref", "parents_json", "tags_json", "metadata_json",
        "record_sha256",
    )

    def __init__(self, path: str | Path, *, timeout_seconds: float = 30.0) -> None:
        self.path = Path(path).expanduser().resolve()
        self.timeout_seconds = timeout_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect_writer()) as db:
            self._ensure_schema(db)

    def _connect_writer(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=self.timeout_seconds, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute(f"PRAGMA busy_timeout={int(self.timeout_seconds * 1000)}")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _connect_reader(self) -> sqlite3.Connection:
        uri = f"file:{self.path.as_posix()}?mode=ro"
        db = sqlite3.connect(uri, uri=True, timeout=self.timeout_seconds, isolation_level=None)
        db.execute("PRAGMA query_only=ON")
        db.execute(f"PRAGMA busy_timeout={int(self.timeout_seconds * 1000)}")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @classmethod
    def _ensure_schema(cls, db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS datasets(
                dataset_key TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                version TEXT NOT NULL,
                scope_kind TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                schema_ref TEXT,
                parents_json TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_datasets_identity ON datasets(dataset_id,version);
            CREATE INDEX IF NOT EXISTS idx_datasets_scope ON datasets(scope_kind,scope_id,dataset_key);
            CREATE TABLE IF NOT EXISTS dataset_tags(
                dataset_key TEXT NOT NULL,
                tag TEXT NOT NULL,
                PRIMARY KEY(dataset_key,tag),
                FOREIGN KEY(dataset_key) REFERENCES datasets(dataset_key) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_dataset_tags_tag ON dataset_tags(tag,dataset_key);
            """
        )
        columns = tuple(row[1] for row in db.execute("PRAGMA table_info(datasets)"))
        if columns != cls._COLUMNS:
            raise DatasetRegistryCorruptionError(
                f"unsupported dataset registry schema columns: {columns!r}"
            )

    @staticmethod
    def _parent_documents(dataset: DatasetVersion) -> tuple[dict[str, str], ...]:
        return tuple(
            {"dataset_id": parent.dataset_id, "version": parent.version}
            for parent in dataset.parent_versions
        )

    @classmethod
    def _document(cls, dataset: DatasetVersion) -> dict[str, object]:
        return {
            "identity": {"dataset_id": dataset.identity.dataset_id, "version": dataset.identity.version},
            "scope": {"kind": dataset.scope.kind.value, "scope_id": dataset.scope.scope_id},
            "content_sha256": dataset.content_sha256,
            "schema_ref": dataset.schema_ref,
            "parent_versions": cls._parent_documents(dataset),
            "tags": dataset.tags,
            "metadata": dataset.metadata,
        }

    @classmethod
    def _record_digest(cls, dataset: DatasetVersion) -> str:
        return canonical_digest(cls._document(dataset))

    @classmethod
    def _encode(cls, dataset: DatasetVersion) -> tuple[object, ...]:
        return (
            dataset.identity.key,
            dataset.identity.dataset_id,
            dataset.identity.version,
            dataset.scope.kind.value,
            dataset.scope.scope_id,
            dataset.content_sha256,
            dataset.schema_ref,
            json.dumps(cls._parent_documents(dataset), ensure_ascii=False, separators=(",", ":")),
            json.dumps(dataset.tags, ensure_ascii=False, separators=(",", ":")),
            json.dumps(dataset.metadata, ensure_ascii=False, separators=(",", ":")),
            cls._record_digest(dataset),
        )

    @staticmethod
    def _decode_parents(raw: object) -> tuple[DatasetIdentity, ...]:
        if not isinstance(raw, list):
            raise TypeError("dataset parents JSON must be a list")
        parents: list[DatasetIdentity] = []
        for row in raw:
            if not isinstance(row, dict) or set(row) != {"dataset_id", "version"}:
                raise TypeError("dataset parent JSON must contain exact identity fields")
            dataset_id = row.get("dataset_id")
            version = row.get("version")
            if not isinstance(dataset_id, str) or not isinstance(version, str):
                raise TypeError("dataset parent identity fields must be strings")
            parents.append(DatasetIdentity(dataset_id, version))
        return tuple(parents)

    @classmethod
    def _decode(cls, row: tuple[object, ...]) -> DatasetVersion:
        try:
            parents_raw = strict_json_loads(require_text(row[7], label="dataset parents_json"))
            tags = strict_json_loads(require_text(row[8], label="dataset tags_json"))
            metadata = strict_json_loads(require_text(row[9], label="dataset metadata_json"))
            parents = cls._decode_parents(parents_raw)
            if not isinstance(tags, list) or not isinstance(metadata, list):
                raise TypeError("dataset collection fields have invalid JSON shape")
            if any(not isinstance(value, str) for value in tags):
                raise TypeError("dataset tags JSON must contain only strings")
            if any(
                not isinstance(pair, list)
                or len(pair) != 2
                or not isinstance(pair[0], str)
                or not isinstance(pair[1], str)
                for pair in metadata
            ):
                raise TypeError("dataset metadata JSON must contain string pairs")
            dataset = DatasetVersion(
                identity=DatasetIdentity(
                    require_text(row[1], label="dataset_id"),
                    require_text(row[2], label="dataset version"),
                ),
                scope=ScopeIdentity(
                    ScopeKind(require_text(row[3], label="dataset scope_kind")),
                    require_text(row[4], label="dataset scope_id"),
                ),
                content_sha256=require_text(row[5], label="dataset content_sha256"),
                schema_ref=require_optional_text(row[6], label="dataset schema_ref"),
                parent_versions=parents,
                tags=tuple(tags),
                metadata=tuple((pair[0], pair[1]) for pair in metadata),
            )
            dataset_key = require_text(row[0], label="dataset_key")
            record_sha256 = require_text(row[10], label="dataset record_sha256")
        except (IndexError, TypeError, ValueError, DataCanonicalDecodingError) as exc:
            raise DatasetRegistryCorruptionError("dataset registry record cannot be decoded") from exc
        if dataset.identity.key != dataset_key:
            raise DatasetRegistryCorruptionError(
                f"dataset key does not match identity: {row[0]!r}"
            )
        if cls._record_digest(dataset) != record_sha256:
            raise DatasetRegistryCorruptionError(
                f"dataset registry record integrity mismatch: {dataset.identity.key}"
            )
        return dataset

    @classmethod
    def _select_columns(cls) -> str:
        return ",".join(cls._COLUMNS)

    def register(self, dataset: DatasetVersion) -> DatasetVersion:
        encoded = self._encode(dataset)
        with closing(self._connect_writer()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    f"SELECT {self._select_columns()} FROM datasets WHERE dataset_key=?",
                    (dataset.identity.key,),
                ).fetchone()
                if row is not None:
                    current = self._decode(row)
                    if current != dataset:
                        raise DatasetRegistryConflict(dataset.identity.key)
                    db.execute("COMMIT")
                    return current
                db.execute("INSERT INTO datasets VALUES(?,?,?,?,?,?,?,?,?,?,?)", encoded)
                db.executemany(
                    "INSERT INTO dataset_tags(dataset_key,tag) VALUES(?,?)",
                    ((dataset.identity.key, tag) for tag in dataset.tags),
                )
                db.execute("COMMIT")
            except BaseException as primary:
                rollback_data_writer(db, primary)
                raise
        return dataset

    def get(self, identity: DatasetIdentity) -> DatasetVersion:
        with closing(self._connect_reader()) as db:
            row = db.execute(
                f"SELECT {self._select_columns()} FROM datasets WHERE dataset_key=?",
                (identity.key,),
            ).fetchone()
        if row is None:
            raise DatasetNotFound(identity.key)
        return self._decode(row)

    def query(self, query: DatasetQuery = DatasetQuery()) -> tuple[DatasetVersion, ...]:
        clauses: list[str] = []
        args: list[object] = []
        join = ""
        if query.tag is not None:
            join = " JOIN dataset_tags t ON t.dataset_key=d.dataset_key"
            clauses.append("t.tag=?")
            args.append(query.tag)
        if query.dataset_id is not None:
            clauses.append("d.dataset_id=?")
            args.append(query.dataset_id)
        if query.scope is not None:
            clauses.extend(("d.scope_kind=?", "d.scope_id=?"))
            args.extend((query.scope.kind.value, query.scope.scope_id))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        columns = ",".join(f"d.{column}" for column in self._COLUMNS)
        args.append(query.limit)
        with closing(self._connect_reader()) as db:
            rows = db.execute(
                f"SELECT {columns} FROM datasets d{join}{where} ORDER BY d.dataset_key LIMIT ?",
                args,
            ).fetchall()
        decoded = tuple(self._decode(row) for row in rows)
        if query.tag is not None and any(query.tag not in row.tags for row in decoded):
            raise DatasetRegistryCorruptionError("dataset tag index disagrees with authoritative record")
        return decoded


__all__ = ["SQLiteDatasetRegistry"]
