from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import ArtifactQuery, ArtifactDescriptor


@runtime_checkable
class ArtifactRegistryPort(Protocol):
    """Immutable artifact-registration authority."""

    def put_many(
        self, artifacts: tuple[ArtifactDescriptor, ...]
    ) -> tuple[ArtifactDescriptor, ...]: ...
    def put(self, artifact: ArtifactDescriptor) -> ArtifactDescriptor: ...
    def get(self, artifact_id: str) -> ArtifactDescriptor: ...
    def query(self, query: ArtifactQuery = ArtifactQuery()) -> tuple[ArtifactDescriptor, ...]: ...


__all__ = ["ArtifactRegistryPort"]
