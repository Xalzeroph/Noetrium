from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.governance.api import ScopeIdentity
from .contracts import ArtifactReference


@runtime_checkable
class ArtifactReferencePort(Protocol):
    def resolve_many(
        self,
        keys: tuple[tuple[str, ScopeIdentity], ...],
    ) -> tuple[ArtifactReference | None, ...]: ...

    def resolve(self, reference_id: str, scope: ScopeIdentity) -> ArtifactReference: ...
    def compare_and_set_many(
        self,
        mutations: tuple[tuple[str, ScopeIdentity, int, str], ...],
    ) -> tuple[ArtifactReference, ...]: ...
    def compare_and_set(
        self,
        reference_id: str,
        scope: ScopeIdentity,
        *,
        expected_generation: int,
        artifact_id: str,
    ) -> ArtifactReference: ...


__all__ = ["ArtifactReferencePort"]
