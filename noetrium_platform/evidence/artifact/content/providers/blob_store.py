from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from threading import RLock

from noetrium_platform.evidence.artifact.content.api import (
    ArtifactBlobRef,
    ArtifactBlobStoreError,
    ArtifactBlobStorePort,
)
from noetrium_platform.foundation.kernel.kernel.durability import InterprocessFileLock
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes


class DirectoryArtifactBlobStore(ArtifactBlobStorePort):
    durability = "crash_durable"

    _LOCK_SHARDS = 256
    _VERIFY_CHUNK_BYTES = 1024 * 1024

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock_root = self.root / ".locks"
        self._lock_root.mkdir(parents=True, exist_ok=True)
        self._local_locks = tuple(
            RLock() for _ in range(self._LOCK_SHARDS)
        )

    @staticmethod
    def _digest(payload: bytes) -> str:
        return sha256(payload).hexdigest()

    def _path(self, digest: str) -> Path:
        return self.root / digest[:2] / f"{digest}.blob"

    @staticmethod
    def _shard_index(digest: str) -> int:
        return int(digest[:2], 16)

    def _lock_path(self, digest: str) -> Path:
        return self._lock_root / f"{digest[:2]}.lock"

    def _verify_existing(
        self,
        path: Path,
        payload: bytes,
        digest: str,
    ) -> None:
        hasher = sha256()
        offset = 0
        identical = True
        try:
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(self._VERIFY_CHUNK_BYTES)
                    if not chunk:
                        break
                    hasher.update(chunk)
                    end = offset + len(chunk)
                    if payload[offset:end] != chunk:
                        identical = False
                    offset = end
        except OSError as exc:
            raise ArtifactBlobStoreError(
                "existing artifact blob cannot be read"
            ) from exc
        if offset != len(payload) or hasher.hexdigest() != digest:
            raise ArtifactBlobStoreError(
                "existing artifact blob failed integrity verification"
            )
        if not identical:
            raise ArtifactBlobStoreError(
                "artifact blob digest collision"
            )

    def put(self, payload: bytes, *, media_type: str) -> ArtifactBlobRef:
        if type(payload) is not bytes:
            raise TypeError("artifact blob payload must be bytes")
        digest = self._digest(payload)
        ref = ArtifactBlobRef(digest, len(payload), media_type)
        path = self._path(digest)
        local_lock = self._local_locks[self._shard_index(digest)]
        with local_lock:
            with InterprocessFileLock(self._lock_path(digest)):
                if path.exists():
                    self._verify_existing(path, payload, digest)
                    return ref
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_replace_bytes(path, payload)
        return ref

    def resolve(
        self,
        content_sha256: str,
        *,
        media_type: str,
    ) -> ArtifactBlobRef:
        if (
            type(content_sha256) is not str
            or len(content_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in content_sha256)
        ):
            raise ValueError(
                "artifact blob resolver content_sha256 must be lowercase SHA-256"
            )
        if type(media_type) is not str or not media_type.strip():
            raise ValueError(
                "artifact blob resolver media_type must be non-empty"
            )
        path = self._path(content_sha256)
        try:
            size_bytes = path.stat().st_size
        except OSError as exc:
            raise ArtifactBlobStoreError("artifact blob is missing") from exc
        ref = ArtifactBlobRef(content_sha256, size_bytes, media_type)
        self.get(ref)
        return ref

    def get(self, ref: ArtifactBlobRef) -> bytes:
        if type(ref) is not ArtifactBlobRef:
            raise TypeError("artifact blob ref must be ArtifactBlobRef")
        try:
            payload = self._path(ref.content_sha256).read_bytes()
        except OSError as exc:
            raise ArtifactBlobStoreError("artifact blob is missing") from exc
        if len(payload) != ref.size_bytes or self._digest(payload) != ref.content_sha256:
            raise ArtifactBlobStoreError("artifact blob integrity mismatch")
        return payload

    def verify(self, ref: ArtifactBlobRef) -> bool:
        try:
            self.get(ref)
        except ArtifactBlobStoreError:
            return False
        return True


__all__ = ["DirectoryArtifactBlobStore"]
