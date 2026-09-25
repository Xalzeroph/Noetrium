from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.evidence.artifact.catalog.api import ArtifactRetention
from .contracts import ArtifactRetentionState


@runtime_checkable
class ArtifactRetentionPort(Protocol):
    def get(self, artifact_id: str) -> ArtifactRetentionState: ...
    def compare_and_set(
        self,
        artifact_id: str,
        *,
        expected_generation: int,
        retention: ArtifactRetention,
        pinned: bool,
        reason_refs: tuple[str, ...] = (),
    ) -> ArtifactRetentionState: ...


__all__ = ["ArtifactRetentionPort"]
