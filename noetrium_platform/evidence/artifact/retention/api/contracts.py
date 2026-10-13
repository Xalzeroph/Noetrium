from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.evidence.artifact.catalog.api import ArtifactRetention


@dataclass(frozen=True, slots=True)
class ArtifactRetentionState:
    artifact_id: str
    retention: ArtifactRetention
    pinned: bool
    generation: int
    reason_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.artifact_id.strip() or isinstance(self.generation, bool) or self.generation <= 0:
            raise ValueError("artifact retention identity/generation is invalid")
        if not isinstance(self.pinned, bool):
            raise TypeError("artifact retention pinned must be bool")
        if any(not ref.strip() for ref in self.reason_refs) or len(set(self.reason_refs)) != len(self.reason_refs):
            raise ValueError("artifact retention reason refs must be non-empty and unique")


class ArtifactRetentionConflict(RuntimeError):
    pass


class ArtifactRetentionCorruptionError(RuntimeError):
    pass


class ArtifactRetentionNotFound(KeyError):
    pass


__all__ = [
    "ArtifactRetentionConflict",
    "ArtifactRetentionCorruptionError",
    "ArtifactRetentionNotFound",
    "ArtifactRetentionState",
]
