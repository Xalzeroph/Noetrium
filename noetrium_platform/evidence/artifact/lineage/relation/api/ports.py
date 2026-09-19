from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity

from .contracts import ArtifactLineageEdge


@runtime_checkable
class ArtifactLineageRelationPort(Protocol):
    """Append-only immutable-content provenance relation authority."""

    def add(self, edge: ArtifactLineageEdge) -> ArtifactLineageEdge: ...

    def parents(
        self,
        child: ArtifactContentIdentity,
    ) -> tuple[ArtifactLineageEdge, ...]: ...

    def children(
        self,
        parent: ArtifactContentIdentity,
    ) -> tuple[ArtifactLineageEdge, ...]: ...


__all__ = ["ArtifactLineageRelationPort"]
