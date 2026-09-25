from __future__ import annotations

from dataclasses import dataclass

from ..api.acquisition import ArtifactAcquisitionPort
from ..providers.download import HttpArtifactAcquirer, HttpOpener


@dataclass(frozen=True, slots=True)
class ArtifactAcquisitionAssembly:
    acquirer: ArtifactAcquisitionPort


def compose_artifact_acquisition(*, opener: HttpOpener | None = None) -> ArtifactAcquisitionAssembly:
    return ArtifactAcquisitionAssembly(acquirer=HttpArtifactAcquirer(opener=opener))


__all__ = ["ArtifactAcquisitionAssembly", "compose_artifact_acquisition"]
