from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from noetrium_platform.evidence.artifact._sqlite_connection import (
    connect_artifact_reader,
    connect_artifact_writer,
    rollback_artifact_writer,
)
from noetrium_platform.evidence.artifact._sqlite_types import require_text
from noetrium_platform.evidence.artifact.content.api import (
    ArtifactStorageBinding,
    ArtifactStorageBindingConflict,
    ArtifactStorageBindingCorruptionError,
    ArtifactStorageBindingNotFound,
    ArtifactStoragePlacementVerifierPort,
    VerifiedArtifactStoragePlacement,
)
from noetrium_platform.foundation.kernel.kernel import strict_finite_json_digest as canonical_digest


class SQLiteArtifactStorageBindingStore:
    """Durable CAS locator authority; every authoritative resolve re-verifies physical bytes."""

    _COLUMNS = (
        "artifact_id", "content_sha256", "storage_provider_id",
        "location", "generation", "record_sha256",
    )

    def __init__(
        self,
        path: str | Path,
        *,
        placement_verifier: ArtifactStoragePlacementVerifierPort,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.timeout_seconds = timeout_seconds
        self._placement_verifier = placement_verifier
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect_writer()) as db:
            self._ensure_schema(db)

    def _connect_writer(self) -> sqlite3.Connection:
        return connect_artifact_writer(self.path, timeout_seconds=self.timeout_seconds)

    def _connect_reader(self) -> sqlite3.Connection:
        return connect_artifact_reader(self.path, timeout_seconds=self.timeout_seconds)

    @classmethod
    def _ensure_schema(cls, db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS artifact_storage_bindings(
                artifact_id TEXT PRIMARY KEY,
                content_sha256 TEXT NOT NULL,
                storage_provider_id TEXT NOT NULL,
                location TEXT NOT NULL,
                generation INTEGER NOT NULL,
                record_sha256 TEXT NOT NULL
            )
            """
        )
        columns = tuple(
            row[1] for row in db.execute("PRAGMA table_info(artifact_storage_bindings)")
        )
        if columns != cls._COLUMNS:
            raise ArtifactStorageBindingCorruptionError(
                f"unsupported artifact storage schema columns: {columns!r}"
            )

    def _verify_placement(
        self,
        *,
        artifact_id: str,
        content_sha256: str,
        storage_provider_id: str,
        location: str,
    ) -> VerifiedArtifactStoragePlacement:
        verified = self._placement_verifier.verify(
            artifact_id=artifact_id,
            content_sha256=content_sha256,
            storage_provider_id=storage_provider_id,
            location=location,
        )
        if verified.artifact_id != artifact_id or verified.content_sha256 != content_sha256:
            raise ArtifactStorageBindingCorruptionError(
                "artifact storage verifier returned mismatched logical/content identity"
            )
        if verified.storage_provider_id != storage_provider_id:
            raise ArtifactStorageBindingCorruptionError(
                "artifact storage verifier returned mismatched provider identity"
            )
        return verified

    def _verify_binding(
        self, binding: ArtifactStorageBinding
    ) -> VerifiedArtifactStoragePlacement:
        verified = self._verify_placement(
            artifact_id=binding.artifact_id,
            content_sha256=binding.content_sha256,
            storage_provider_id=binding.storage_provider_id,
            location=binding.location,
        )
        if verified.location != binding.location:
            raise ArtifactStorageBindingCorruptionError(
                "artifact storage verifier changed a persisted canonical location"
            )
        return verified

    @staticmethod
    def _document(binding: ArtifactStorageBinding) -> dict[str, object]:
        return {
            "artifact_id": binding.artifact_id,
            "content_sha256": binding.content_sha256,
            "storage_provider_id": binding.storage_provider_id,
            "location": binding.location,
            "generation": binding.generation,
        }

    @classmethod
    def _record_digest(cls, binding: ArtifactStorageBinding) -> str:
        return canonical_digest(cls._document(binding))

    @classmethod
    def _encode(cls, binding: ArtifactStorageBinding) -> tuple[object, ...]:
        return (
            binding.artifact_id,
            binding.content_sha256,
            binding.storage_provider_id,
            binding.location,
            binding.generation,
            cls._record_digest(binding),
        )

    @classmethod
    def _decode(cls, row: tuple[object, ...]) -> ArtifactStorageBinding:
        try:
            generation = row[4]
            if isinstance(generation, bool) or not isinstance(generation, int):
                raise TypeError("artifact storage generation must be an integer")
            binding = ArtifactStorageBinding(
                artifact_id=require_text(row[0], label="artifact storage artifact_id"),
                content_sha256=require_text(row[1], label="artifact storage content_sha256"),
                storage_provider_id=require_text(row[2], label="artifact storage provider_id"),
                location=require_text(row[3], label="artifact storage location"),
                generation=generation,
            )
            stored_digest = require_text(row[5], label="artifact storage record_sha256")
        except (IndexError, TypeError, ValueError) as exc:
            raise ArtifactStorageBindingCorruptionError(
                "artifact storage binding cannot be decoded"
            ) from exc
        if cls._record_digest(binding) != stored_digest:
            raise ArtifactStorageBindingCorruptionError(
                f"artifact storage binding integrity mismatch: {binding.artifact_id}"
            )
        return binding

    @classmethod
    def _select_columns(cls) -> str:
        return ",".join(cls._COLUMNS)

    def bind(
        self,
        *,
        artifact_id: str,
        content_sha256: str,
        storage_provider_id: str,
        location: str,
    ) -> ArtifactStorageBinding:
        verified = self._verify_placement(
            artifact_id=artifact_id,
            content_sha256=content_sha256,
            storage_provider_id=storage_provider_id,
            location=location,
        )
        proposed = ArtifactStorageBinding(
            artifact_id=verified.artifact_id,
            content_sha256=verified.content_sha256,
            storage_provider_id=verified.storage_provider_id,
            location=verified.location,
            generation=1,
        )
        with closing(self._connect_writer()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    f"SELECT {self._select_columns()} FROM artifact_storage_bindings WHERE artifact_id=?",
                    (artifact_id,),
                ).fetchone()
                if row is not None:
                    current = self._decode(row)
                    if current != proposed:
                        raise ArtifactStorageBindingConflict(artifact_id)
                    self._verify_binding(current)
                    db.execute("COMMIT")
                else:
                    db.execute(
                        "INSERT INTO artifact_storage_bindings VALUES(?,?,?,?,?,?)",
                        self._encode(proposed),
                    )
                    self._verify_binding(proposed)
                    db.execute("COMMIT")
            except BaseException as primary:
                rollback_artifact_writer(db, primary)
                raise
        return self.resolve(artifact_id)

    def _resolve_binding_record(self, artifact_id: str) -> ArtifactStorageBinding:
        if not artifact_id.strip():
            raise ValueError("artifact storage lookup identity must be non-empty")
        with closing(self._connect_reader()) as db:
            row = db.execute(
                f"SELECT {self._select_columns()} FROM artifact_storage_bindings WHERE artifact_id=?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise ArtifactStorageBindingNotFound(artifact_id)
        return self._decode(row)

    def resolve(self, artifact_id: str) -> ArtifactStorageBinding:
        binding = self._resolve_binding_record(artifact_id)
        self._verify_binding(binding)
        return binding

    def relocate(
        self,
        artifact_id: str,
        *,
        expected_generation: int,
        storage_provider_id: str,
        location: str,
    ) -> ArtifactStorageBinding:
        if isinstance(expected_generation, bool) or not isinstance(expected_generation, int) or expected_generation <= 0:
            raise ValueError("expected_generation must be a positive integer")
        if not storage_provider_id.strip() or not location.strip():
            raise ValueError("artifact storage provider/location must be non-empty")
        observed = self._resolve_binding_record(artifact_id)
        if observed.generation != expected_generation:
            raise ArtifactStorageBindingConflict(
                f"{artifact_id}: expected generation {expected_generation}, got {observed.generation}"
            )
        verified = self._verify_placement(
            artifact_id=artifact_id,
            content_sha256=observed.content_sha256,
            storage_provider_id=storage_provider_id,
            location=location,
        )
        with closing(self._connect_writer()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    f"SELECT {self._select_columns()} FROM artifact_storage_bindings WHERE artifact_id=?",
                    (artifact_id,),
                ).fetchone()
                if row is None:
                    raise ArtifactStorageBindingNotFound(artifact_id)
                current = self._decode(row)
                if current.generation != expected_generation:
                    raise ArtifactStorageBindingConflict(
                        f"{artifact_id}: expected generation {expected_generation}, got {current.generation}"
                    )
                if current.content_sha256 != observed.content_sha256:
                    raise ArtifactStorageBindingCorruptionError(
                        f"artifact storage content identity changed during relocation: {artifact_id}"
                    )
                if (
                    current.storage_provider_id == verified.storage_provider_id
                    and current.location == verified.location
                ):
                    self._verify_binding(current)
                    db.execute("COMMIT")
                    return self.resolve(artifact_id)
                updated = ArtifactStorageBinding(
                    artifact_id=current.artifact_id,
                    content_sha256=current.content_sha256,
                    storage_provider_id=verified.storage_provider_id,
                    location=verified.location,
                    generation=current.generation + 1,
                )
                self._verify_binding(updated)
                cursor = db.execute(
                    "UPDATE artifact_storage_bindings SET content_sha256=?,storage_provider_id=?,location=?,generation=?,record_sha256=? WHERE artifact_id=? AND generation=?",
                    (
                        updated.content_sha256,
                        updated.storage_provider_id,
                        updated.location,
                        updated.generation,
                        self._record_digest(updated),
                        updated.artifact_id,
                        expected_generation,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ArtifactStorageBindingConflict(
                        f"{artifact_id}: storage generation changed during relocation"
                    )
                self._verify_binding(updated)
                db.execute("COMMIT")
            except BaseException as primary:
                rollback_artifact_writer(db, primary)
                raise
        return self.resolve(artifact_id)


__all__ = ["SQLiteArtifactStorageBindingStore"]
