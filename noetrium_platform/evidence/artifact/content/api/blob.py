from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import require_sha256


@dataclass(frozen=True, slots=True)
class ArtifactBlobRef:
    content_sha256: str
    size_bytes: int
    media_type: str

    def __post_init__(self) -> None:
        require_sha256(self.content_sha256, "artifact blob content_sha256")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("artifact blob size_bytes must be a non-negative integer")
        if type(self.media_type) is not str or not self.media_type.strip():
            raise ValueError("artifact blob media_type must be non-empty")


class ArtifactBlobStoreError(RuntimeError):
    pass

@runtime_checkable
class ArtifactBlobStorePort(Protocol):
    durability: str

    def put(self, payload: bytes, *, media_type: str) -> ArtifactBlobRef: ...

    def get(self, ref: ArtifactBlobRef) -> bytes: ...

    def verify(self, ref: ArtifactBlobRef) -> bool: ...


__all__ = [
    "ArtifactBlobRef",
    "ArtifactBlobStoreError",
    "ArtifactBlobStorePort",
]
