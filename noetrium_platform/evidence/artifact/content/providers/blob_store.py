from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from noetrium_platform.evidence.artifact.content.api import (
    ArtifactBlobRef,
    ArtifactBlobStoreError,
    ArtifactBlobStorePort,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes


class DirectoryArtifactBlobStore(ArtifactBlobStorePort):
    durability = "crash_durable"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _digest(payload: bytes) -> str:
        return sha256(payload).hexdigest()

    def _path(self, digest: str) -> Path:
        return self.root / digest[:2] / f"{digest}.blob"

    def put(self, payload: bytes, *, media_type: str) -> ArtifactBlobRef:
        if type(payload) is not bytes:
            raise TypeError("artifact blob payload must be bytes")
        digest = self._digest(payload)
        ref = ArtifactBlobRef(digest, len(payload), media_type)
        path = self._path(digest)
        if path.exists():
            current = path.read_bytes()
            if len(current) != len(payload) or self._digest(current) != digest:
                raise ArtifactBlobStoreError("existing artifact blob failed integrity verification")
            if current != payload:
                raise ArtifactBlobStoreError("artifact blob digest collision")
            return ref
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_replace_bytes(path, payload)
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
