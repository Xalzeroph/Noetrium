from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Mapping

from noetrium_platform.foundation.kernel.kernel import (
    canonical_bytes,
    canonical_digest,
    require_sha256,
    strict_json_loads,
    thaw_json,
)
from noetrium_platform.foundation.kernel.kernel.durability import (
    atomic_replace_bytes,
    InterprocessFileLock,
)

from .research_checkpoint import (
    ResearchGraphCheckpoint,
    ResearchGraphCheckpointCorruptionError,
    ResearchGraphCheckpointStorePort,
)


class DirectoryResearchGraphCheckpointStore(ResearchGraphCheckpointStorePort):
    """Crash-durable content-addressed Research execution checkpoint proof store."""

    durability = "crash_durable_file"
    _POINTER_SCHEMA = "noetrium.research-graph-checkpoint-pointer.v1"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().absolute()
        self.objects = self.root / "objects"
        self.pointers = self.root / "latest"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.pointers.mkdir(parents=True, exist_ok=True)
        self._process_lock_path = self.root / ".research-checkpoint.lock"
        self._lock = RLock()

    @staticmethod
    def _scope_digest(
        execution_cut_id: str,
        selected_node_ids: tuple[str, ...],
    ) -> str:
        require_sha256(execution_cut_id, "graph checkpoint execution_cut_id")
        ordered = tuple(sorted(selected_node_ids))
        if not ordered or len(ordered) != len(set(ordered)):
            raise ValueError("graph checkpoint selection must be non-empty and unique")
        return canonical_digest(
            {
                "execution_cut_id": execution_cut_id,
                "selected_node_ids": ordered,
            }
        )

    def _object_path(self, checkpoint_digest: str) -> Path:
        require_sha256(checkpoint_digest, "graph checkpoint digest")
        return self.objects / f"{checkpoint_digest}.json"

    def _pointer_path(self, scope_digest: str) -> Path:
        require_sha256(scope_digest, "graph checkpoint scope digest")
        return self.pointers / f"{scope_digest}.json"

    @staticmethod
    def _decode_checkpoint(
        raw: bytes,
        *,
        expected_digest: str,
    ) -> ResearchGraphCheckpoint:
        try:
            document = strict_json_loads(raw)
            if not isinstance(document, Mapping):
                raise TypeError("checkpoint document must be an object")
            checkpoint = ResearchGraphCheckpoint.from_document(document)
        except BaseException as exc:
            if isinstance(exc, ResearchGraphCheckpointCorruptionError):
                raise
            raise ResearchGraphCheckpointCorruptionError(
                "Research execution graph checkpoint failed schema/integrity validation"
            ) from exc
        if checkpoint.checkpoint_digest != expected_digest:
            raise ResearchGraphCheckpointCorruptionError(
                "Research execution graph checkpoint object identity drifted"
            )
        if canonical_bytes(checkpoint.to_document()) != raw:
            raise ResearchGraphCheckpointCorruptionError(
                "Research execution graph checkpoint is not canonical JSON"
            )
        return checkpoint

    @staticmethod
    def read_object(path: str | Path) -> ResearchGraphCheckpoint:
        """Decode one existing immutable object without constructing a writer store."""
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file():
            raise ResearchGraphCheckpointCorruptionError(
                "checkpoint object must be an existing regular file"
            )
        require_sha256(candidate.stem, "graph checkpoint digest")
        return DirectoryResearchGraphCheckpointStore._decode_checkpoint(
            candidate.read_bytes(), expected_digest=candidate.stem
        )

    @staticmethod
    def read_document(path: str | Path):
        """Read a validated checkpoint as ordinary JSON for read-only clients."""
        return thaw_json(
            DirectoryResearchGraphCheckpointStore.read_object(path).to_document()
        )

    def _load_unlocked(
        self,
        checkpoint_digest: str,
    ) -> ResearchGraphCheckpoint | None:
        path = self._object_path(checkpoint_digest)
        if not path.exists():
            return None
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ResearchGraphCheckpointCorruptionError(
                "Research execution graph checkpoint object is unreadable"
            ) from exc
        return self._decode_checkpoint(raw, expected_digest=checkpoint_digest)

    def load(self, checkpoint_digest: str) -> ResearchGraphCheckpoint | None:
        with self._lock:
            with InterprocessFileLock(self._process_lock_path):
                return self._load_unlocked(checkpoint_digest)

    def latest(
        self,
        execution_cut_id: str,
        selected_node_ids: tuple[str, ...],
    ) -> ResearchGraphCheckpoint | None:
        scope_digest = self._scope_digest(execution_cut_id, selected_node_ids)
        path = self._pointer_path(scope_digest)
        with self._lock:
            with InterprocessFileLock(self._process_lock_path):
                if not path.exists():
                    return None
                try:
                    raw = path.read_bytes()
                    document = strict_json_loads(raw)
                    if not isinstance(document, Mapping):
                        raise TypeError("checkpoint pointer must be an object")
                    if document.get("schema") != self._POINTER_SCHEMA:
                        raise ValueError("unsupported checkpoint pointer schema")
                    if document.get("scope_digest") != scope_digest:
                        raise ValueError("checkpoint pointer scope drifted")
                    checkpoint_digest = str(document["checkpoint_digest"])
                    require_sha256(checkpoint_digest, "checkpoint pointer digest")
                    if canonical_bytes(dict(document)) != raw:
                        raise ValueError("checkpoint pointer is not canonical JSON")
                except BaseException as exc:
                    raise ResearchGraphCheckpointCorruptionError(
                        "Research execution graph checkpoint pointer is corrupt"
                    ) from exc
                checkpoint = self._load_unlocked(checkpoint_digest)
                if checkpoint is None:
                    raise ResearchGraphCheckpointCorruptionError(
                        "Research execution graph checkpoint pointer references missing object"
                    )
                if checkpoint.scope_digest != scope_digest:
                    raise ResearchGraphCheckpointCorruptionError(
                        "Research execution graph checkpoint pointer/object scope mismatch"
                    )
                return checkpoint

    def publish(
        self,
        checkpoint: ResearchGraphCheckpoint,
    ) -> ResearchGraphCheckpoint:
        if not isinstance(checkpoint, ResearchGraphCheckpoint):
            raise TypeError("graph checkpoint store accepts ResearchGraphCheckpoint")
        scope_digest = checkpoint.scope_digest
        object_path = self._object_path(checkpoint.checkpoint_digest)
        pointer_path = self._pointer_path(scope_digest)
        encoded = canonical_bytes(checkpoint.to_document())

        with self._lock:
            with InterprocessFileLock(self._process_lock_path):
                existing = self._load_unlocked(checkpoint.checkpoint_digest)
                if existing is not None and existing != checkpoint:
                    raise ResearchGraphCheckpointCorruptionError(
                        "checkpoint digest already names different content"
                    )
                if existing is None:
                    atomic_replace_bytes(object_path, encoded)

                current: ResearchGraphCheckpoint | None = None
                if pointer_path.exists():
                    try:
                        pointer = strict_json_loads(pointer_path.read_bytes())
                        if not isinstance(pointer, Mapping):
                            raise TypeError("checkpoint pointer must be an object")
                        if pointer.get("schema") != self._POINTER_SCHEMA:
                            raise ValueError("unsupported checkpoint pointer schema")
                        if pointer.get("scope_digest") != scope_digest:
                            raise ValueError("checkpoint pointer scope drifted")
                        prior_digest = str(pointer["checkpoint_digest"])
                        require_sha256(prior_digest, "checkpoint pointer digest")
                    except BaseException as exc:
                        raise ResearchGraphCheckpointCorruptionError(
                            "Research execution graph checkpoint pointer is corrupt"
                        ) from exc
                    current = self._load_unlocked(prior_digest)
                    if current is None:
                        raise ResearchGraphCheckpointCorruptionError(
                            "checkpoint pointer references missing object"
                        )

                if current is not None:
                    if checkpoint.snapshot_generation < current.snapshot_generation:
                        raise ValueError(
                            "graph checkpoint snapshot generation moved backwards"
                        )
                    if checkpoint.control_generation < current.control_generation:
                        raise ValueError(
                            "graph checkpoint control generation moved backwards"
                        )
                    if (
                        checkpoint.snapshot_generation == current.snapshot_generation
                        and checkpoint.control_generation == current.control_generation
                        and checkpoint.checkpoint_digest != current.checkpoint_digest
                    ):
                        raise ValueError(
                            "graph checkpoint generation has conflicting content"
                        )
                    if checkpoint.checkpoint_digest == current.checkpoint_digest:
                        return current

                atomic_replace_bytes(
                    pointer_path,
                    canonical_bytes(
                        {
                            "schema": self._POINTER_SCHEMA,
                            "scope_digest": scope_digest,
                            "checkpoint_digest": checkpoint.checkpoint_digest,
                        }
                    ),
                )
                return checkpoint


__all__ = ["DirectoryResearchGraphCheckpointStore"]
