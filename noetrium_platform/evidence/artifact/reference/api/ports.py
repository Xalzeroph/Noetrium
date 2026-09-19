from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.scope.api import ScopeIdentity
from .contracts import ArtifactReference


@runtime_checkable
class ArtifactReferencePort(Protocol):
    def resolve(self, reference_id: str, scope: ScopeIdentity) -> ArtifactReference: ...
    def compare_and_set(
        self,
        reference_id: str,
        scope: ScopeIdentity,
        *,
        expected_generation: int,
        artifact_id: str,
    ) -> ArtifactReference: ...


__all__ = ["ArtifactReferencePort"]
