from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.foundation.scope.api import ScopeIdentity


class ArtifactKind(StrEnum):
    SCIENTIFIC = "scientific"
    RUNTIME = "runtime"
    DIAGNOSTIC = "diagnostic"
    DATASET = "dataset"
    MODEL = "model"
    CHECKPOINT = "checkpoint"
    REPORT = "report"
    PUBLICATION = "publication"


class ArtifactRetention(StrEnum):
    EPHEMERAL = "ephemeral"
    RUN = "run"
    PROJECT = "project"
    RELEASE = "release"
    PERMANENT = "permanent"


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_id: str
    kind: ArtifactKind
    scope: ScopeIdentity
    digest: str
    producer_component_id: str
    producer_operation_id: str | None = None
    media_type: str = "application/octet-stream"
    lineage: tuple[ArtifactContentIdentity, ...] = ()
    # Immutable registration-time retention declaration. Mutable effective
    # retention/pinning belongs to artifact.retention, never back to this record.
    retention: ArtifactRetention = ArtifactRetention.PROJECT
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        """Validate every lineage and metadata entry before accepting artifact authority.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: N is lineage plus metadata cardinality; non-empty and uniqueness checks must inspect the complete caller-supplied authority.
        """
        if not self.artifact_id.strip():
            raise ValueError("artifact identity must be non-empty")
        if len(self.digest) != 64 or any(char not in "0123456789abcdef" for char in self.digest):
            raise ValueError("artifact digest must be lowercase SHA-256")
        if not self.producer_component_id.strip() or not self.media_type.strip():
            raise ValueError("artifact producer_component_id and media_type must be non-empty")
        if self.producer_operation_id is not None and not self.producer_operation_id.strip():
            raise ValueError("artifact producer_operation_id must be non-empty when present")
        if any(type(ref) is not ArtifactContentIdentity for ref in self.lineage):
            raise TypeError("artifact catalog lineage must contain ArtifactContentIdentity values")
        if len(set(self.lineage)) != len(self.lineage):
            raise ValueError("artifact catalog lineage references must be unique")
        ordered = tuple(sorted(self.lineage, key=lambda ref: (ref.artifact_id, ref.content_sha256)))
        if self.lineage != ordered:
            raise ValueError("artifact catalog lineage must be canonically ordered")
        if any(ref.artifact_id == self.artifact_id for ref in self.lineage):
            raise ValueError("artifact catalog lineage cannot contain the artifact itself")
        keys = [key for key, _ in self.metadata]
        if any(not key.strip() for key in keys) or len(set(keys)) != len(keys):
            raise ValueError("artifact metadata keys must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class ArtifactQuery:
    scope: ScopeIdentity | None = None
    kind: ArtifactKind | None = None
    producer_component_id: str | None = None
    limit: int = 1000

    def __post_init__(self) -> None:
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or not 1 <= self.limit <= 10_000:
            raise ValueError("artifact query limit must be an integer in [1, 10000]")


__all__ = ["ArtifactKind", "ArtifactQuery", "ArtifactRecord", "ArtifactRetention"]
