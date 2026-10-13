from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


def _require_sha256(value: str, *, label: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class VerifiedArtifactStoragePlacement:
    """Provider-produced snapshot proof that expected artifact bytes exist at one placement."""

    artifact_id: str
    content_sha256: str
    storage_provider_id: str
    location: str
    size_bytes: int

    def __post_init__(self) -> None:
        if not self.artifact_id.strip():
            raise ValueError("verified artifact placement artifact_id must be non-empty")
        _require_sha256(self.content_sha256, label="verified artifact placement content_sha256")
        if not self.storage_provider_id.strip() or not self.location.strip():
            raise ValueError("verified artifact placement provider/location must be non-empty")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ValueError("verified artifact placement size_bytes must be a non-negative integer")


class ArtifactStorageVerificationError(RuntimeError):
    """Physical storage verification failed before placement authority changed."""

    def __init__(self, code: str, message: str) -> None:
        if not code.strip():
            raise ValueError("artifact storage verification code must be non-empty")
        self.code = code
        super().__init__(f"artifact storage verification failed [{code}]: {message}")


@runtime_checkable
class ArtifactStoragePlacementVerifierPort(Protocol):
    def verify(
        self,
        *,
        artifact_id: str,
        content_sha256: str,
        storage_provider_id: str,
        location: str,
    ) -> VerifiedArtifactStoragePlacement: ...


@dataclass(frozen=True, slots=True)
class ArtifactStorageBinding:
    """Physical storage binding for immutable artifact content."""

    artifact_id: str
    content_sha256: str
    storage_provider_id: str
    location: str
    generation: int

    def __post_init__(self) -> None:
        if not self.artifact_id.strip():
            raise ValueError("artifact storage artifact_id must be non-empty")
        _require_sha256(self.content_sha256, label="artifact storage content_sha256")
        if not self.storage_provider_id.strip() or not self.location.strip():
            raise ValueError("artifact storage provider/location must be non-empty")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation <= 0:
            raise ValueError("artifact storage generation must be a positive integer")


class ArtifactStorageBindingConflict(RuntimeError):
    pass


class ArtifactStorageBindingCorruptionError(RuntimeError):
    pass


class ArtifactStorageBindingNotFound(KeyError):
    pass


@runtime_checkable
class ArtifactStorageBindingPort(Protocol):
    def bind(
        self,
        *,
        artifact_id: str,
        content_sha256: str,
        storage_provider_id: str,
        location: str,
    ) -> ArtifactStorageBinding: ...

    def resolve(self, artifact_id: str) -> ArtifactStorageBinding: ...

    def relocate(
        self,
        artifact_id: str,
        *,
        expected_generation: int,
        storage_provider_id: str,
        location: str,
    ) -> ArtifactStorageBinding: ...


__all__ = [
    "ArtifactStorageBinding",
    "ArtifactStorageBindingConflict",
    "ArtifactStorageBindingCorruptionError",
    "ArtifactStorageBindingNotFound",
    "ArtifactStorageBindingPort",
    "ArtifactStoragePlacementVerifierPort",
    "ArtifactStorageVerificationError",
    "VerifiedArtifactStoragePlacement",
]
