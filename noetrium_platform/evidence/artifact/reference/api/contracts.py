from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.scope.api import ScopeIdentity


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    reference_id: str
    scope: ScopeIdentity
    artifact_id: str
    generation: int

    def __post_init__(self) -> None:
        if not self.reference_id.strip() or not self.artifact_id.strip():
            raise ValueError("artifact reference identities must be non-empty")
        if isinstance(self.generation, bool) or self.generation <= 0:
            raise ValueError("artifact reference generation must be a positive integer")


class ArtifactReferenceConflict(RuntimeError):
    pass


class ArtifactReferenceCorruptionError(RuntimeError):
    pass


class ArtifactReferenceNotFound(KeyError):
    pass


__all__ = [
    "ArtifactReference",
    "ArtifactReferenceConflict",
    "ArtifactReferenceCorruptionError",
    "ArtifactReferenceNotFound",
]
