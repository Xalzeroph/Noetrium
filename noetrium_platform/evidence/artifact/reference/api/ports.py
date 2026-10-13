from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.governance.api import NoetriumUnit
from .contracts import ArtifactReference


@runtime_checkable
class ArtifactReferencePort(Protocol):
    def resolve_many(
        self,
        keys: tuple[tuple[str, NoetriumUnit], ...],
    ) -> tuple[ArtifactReference | None, ...]: ...

    def resolve(self, reference_id: str, scope: NoetriumUnit) -> ArtifactReference: ...
    def compare_and_set_many(
        self,
        mutations: tuple[tuple[str, NoetriumUnit, int, str], ...],
    ) -> tuple[ArtifactReference, ...]: ...
    def compare_and_set(
        self,
        reference_id: str,
        scope: NoetriumUnit,
        *,
        expected_generation: int,
        artifact_id: str,
    ) -> ArtifactReference: ...


__all__ = ["ArtifactReferencePort"]
