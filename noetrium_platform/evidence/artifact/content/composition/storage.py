from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..api.storage import (
    ArtifactStorageBindingPort,
    ArtifactStoragePlacementVerifierPort,
)
from ..providers.filesystem_storage import FilesystemArtifactStoragePlacementVerifier
from ..providers.sqlite_storage import SQLiteArtifactStorageBindingStore


@dataclass(frozen=True, slots=True)
class ArtifactStorageBindingAssembly:
    bindings: ArtifactStorageBindingPort
    placement_verifier: ArtifactStoragePlacementVerifierPort


def compose_filesystem_artifact_storage_bindings(
    registry_path: str | Path,
    *,
    placement_verifier: ArtifactStoragePlacementVerifierPort | None = None,
    timeout_seconds: float = 30.0,
) -> ArtifactStorageBindingAssembly:
    """Wire durable binding authority to verified local-filesystem placement."""

    verifier = placement_verifier or FilesystemArtifactStoragePlacementVerifier()
    bindings = SQLiteArtifactStorageBindingStore(
        registry_path,
        placement_verifier=verifier,
        timeout_seconds=timeout_seconds,
    )
    return ArtifactStorageBindingAssembly(
        bindings=bindings,
        placement_verifier=verifier,
    )


__all__ = [
    "ArtifactStorageBindingAssembly",
    "compose_filesystem_artifact_storage_bindings",
]
