from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from noetrium_platform.evidence.artifact.catalog.api import ArtifactRetention
from noetrium_platform.evidence.artifact.retention.api import (
    ArtifactRetentionConflict,
    ArtifactRetentionCorruptionError,
    ArtifactRetentionNotFound,
    ArtifactRetentionState,
)
from noetrium_platform.foundation.kernel.kernel import strict_finite_json_digest as canonical_digest
from noetrium_platform.evidence.artifact._sqlite_connection import connect_artifact_reader, connect_artifact_writer, rollback_artifact_writer
from noetrium_platform.evidence.artifact._sqlite_types import require_integer, require_text


class SQLiteArtifactRetentionStore:
    """Current retention/pinning CAS authority with row-integrity verification."""

    _COLUMNS = (
        "artifact_id", "retention", "pinned", "generation", "reason_refs_json", "record_sha256",
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
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS artifact_retention(
                artifact_id TEXT PRIMARY KEY,
                retention TEXT NOT NULL,
                pinned INTEGER NOT NULL CHECK(pinned IN (0,1)),
                generation INTEGER NOT NULL CHECK(generation > 0),
                reason_refs_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL
            )
            """
        )
        columns = tuple(row[1] for row in db.execute("PRAGMA table_info(artifact_retention)"))
        if columns != cls._COLUMNS:
            raise ArtifactRetentionCorruptionError(
                f"unsupported artifact retention schema columns: {columns!r}"
            )

    @staticmethod
    def _document(state: ArtifactRetentionState) -> dict[str, object]:
        return {
            "artifact_id": state.artifact_id,
            "retention": state.retention.value,
            "pinned": state.pinned,
            "generation": state.generation,
            "reason_refs": state.reason_refs,
        }

    @classmethod
    def _record_digest(cls, state: ArtifactRetentionState) -> str:
        return canonical_digest(cls._document(state))

    @classmethod
    def _encode(cls, state: ArtifactRetentionState) -> tuple[object, ...]:
        return (
            state.artifact_id,
            state.retention.value,
            int(state.pinned),
            state.generation,
            json.dumps(state.reason_refs, ensure_ascii=False, separators=(",", ":")),
            cls._record_digest(state),
        )

    @classmethod
    def _decode(cls, row: tuple[object, ...]) -> ArtifactRetentionState:
        try:
            pinned_raw = require_integer(row[2], label="artifact retention pinned")
            if pinned_raw not in (0, 1):
                raise ValueError("pinned must be 0 or 1")
            refs = json.loads(
                require_text(row[4], label="artifact retention reason_refs_json")
            )
            if not isinstance(refs, list):
                raise TypeError("reason_refs_json must decode to a list")
            if any(not isinstance(value, str) for value in refs):
                raise TypeError("artifact retention reason refs must be strings")
            state = ArtifactRetentionState(
                artifact_id=require_text(row[0], label="artifact retention artifact_id"),
                retention=ArtifactRetention(
                    require_text(row[1], label="artifact retention policy")
                ),
                pinned=bool(pinned_raw),
                generation=require_integer(
                    row[3], label="artifact retention generation", minimum=1
                ),
                reason_refs=tuple(refs),
            )
            stored_digest = require_text(row[5], label="artifact retention record_sha256")
        except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ArtifactRetentionCorruptionError("stored artifact retention state cannot be decoded") from exc
        if cls._record_digest(state) != stored_digest:
            raise ArtifactRetentionCorruptionError(
                f"artifact retention integrity mismatch: {state.artifact_id}"
            )
        return state

    @classmethod
    def _select(cls, db: sqlite3.Connection, artifact_id: str) -> tuple[object, ...] | None:
        return db.execute(
            f"SELECT {','.join(cls._COLUMNS)} FROM artifact_retention WHERE artifact_id=?",
            (artifact_id,),
        ).fetchone()

    def get(self, artifact_id: str) -> ArtifactRetentionState:
        if not artifact_id.strip():
            raise ValueError("artifact retention lookup identity must be non-empty")
        with closing(self._connect_reader()) as db:
            row = self._select(db, artifact_id)
        if row is None:
            raise ArtifactRetentionNotFound(artifact_id)
        return self._decode(row)

    def compare_and_set(
        self,
        artifact_id: str,
        *,
        expected_generation: int,
        retention: ArtifactRetention,
        pinned: bool,
        reason_refs: tuple[str, ...] = (),
    ) -> ArtifactRetentionState:
        if isinstance(expected_generation, bool) or expected_generation < 0:
            raise ValueError("artifact retention expected_generation must be a non-negative integer")
        if not isinstance(pinned, bool):
            raise TypeError("artifact retention pinned must be bool")
        candidate_generation = 1 if expected_generation == 0 else expected_generation + 1
        candidate = ArtifactRetentionState(
            artifact_id,
            retention,
            pinned,
            candidate_generation,
            reason_refs,
        )
        with closing(self._connect_writer()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = self._select(db, artifact_id)
                if row is None:
                    if expected_generation != 0:
                        raise ArtifactRetentionConflict(
                            f"missing retention state {artifact_id!r}; expected generation {expected_generation}"
                        )
                    db.execute(
                        "INSERT INTO artifact_retention VALUES(?,?,?,?,?,?)",
                        self._encode(candidate),
                    )
                    db.execute("COMMIT")
                    return candidate
                current = self._decode(row)
                if current.generation != expected_generation:
                    raise ArtifactRetentionConflict(
                        f"retention generation conflict: expected {expected_generation}, actual {current.generation}"
                    )
                if (
                    current.retention is retention
                    and current.pinned is pinned
                    and current.reason_refs == reason_refs
                ):
                    db.execute("COMMIT")
                    return current
                updated = ArtifactRetentionState(
                    artifact_id,
                    retention,
                    pinned,
                    current.generation + 1,
                    reason_refs,
                )
                db.execute(
                    "UPDATE artifact_retention SET retention=?,pinned=?,generation=?,reason_refs_json=?,record_sha256=? "
                    "WHERE artifact_id=?",
                    (
                        updated.retention.value,
                        int(updated.pinned),
                        updated.generation,
                        json.dumps(updated.reason_refs, ensure_ascii=False, separators=(",", ":")),
                        self._record_digest(updated),
                        artifact_id,
                    ),
                )
                db.execute("COMMIT")
                return updated
            except BaseException as primary:
                rollback_artifact_writer(db, primary)
                raise


__all__ = ["SQLiteArtifactRetentionStore"]
