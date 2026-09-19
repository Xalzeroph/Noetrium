from __future__ import annotations

import heapq

from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactNotFound,
    ArtifactQuery,
    ArtifactRecord,
    ArtifactRegistryConflict,
)


class InMemoryArtifactRegistry:
    """Process-local test/dev implementation of the immutable catalog contract."""

    def __init__(self) -> None:
        self._items: dict[str, ArtifactRecord] = {}

    def put(self, artifact: ArtifactRecord) -> ArtifactRecord:
        current = self._items.get(artifact.artifact_id)
        if current is not None and current != artifact:
            raise ArtifactRegistryConflict(artifact.artifact_id)
        self._items[artifact.artifact_id] = artifact
        return artifact

    def get(self, artifact_id: str) -> ArtifactRecord:
        try:
            return self._items[artifact_id]
        except KeyError as exc:
            raise ArtifactNotFound(artifact_id) from exc

    def query(self, query: ArtifactQuery = ArtifactQuery()) -> tuple[ArtifactRecord, ...]:
        rows = self._items.values()
        if query.scope is not None:
            rows = (row for row in rows if row.scope == query.scope)
        if query.kind is not None:
            rows = (row for row in rows if row.kind is query.kind)
        if query.producer_component_id is not None:
            rows = (row for row in rows if row.producer_component_id == query.producer_component_id)
        return tuple(heapq.nsmallest(query.limit, rows, key=lambda row: row.artifact_id))


__all__ = ["InMemoryArtifactRegistry"]
