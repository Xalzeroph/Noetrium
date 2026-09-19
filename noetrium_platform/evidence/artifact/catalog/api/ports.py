from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import ArtifactQuery, ArtifactRecord


@runtime_checkable
class ArtifactRegistryPort(Protocol):
    """Immutable artifact-registration authority."""

    def put(self, artifact: ArtifactRecord) -> ArtifactRecord: ...
    def get(self, artifact_id: str) -> ArtifactRecord: ...
    def query(self, query: ArtifactQuery = ArtifactQuery()) -> tuple[ArtifactRecord, ...]: ...


__all__ = ["ArtifactRegistryPort"]
