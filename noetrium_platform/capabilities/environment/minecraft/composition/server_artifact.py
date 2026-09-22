from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.substrate.api import (
    ArtifactAcquisitionPort,
    ArtifactHttpOpener,
)

from ..providers.server_artifact import OfficialMinecraftServerArtifactProvider


@dataclass(frozen=True, slots=True)
class MinecraftServerArtifactAssembly:
    provider: OfficialMinecraftServerArtifactProvider


def compose_official_minecraft_server_artifacts(
    *,
    acquisition: ArtifactAcquisitionPort,
    metadata_opener: ArtifactHttpOpener | None = None,
) -> MinecraftServerArtifactAssembly:
    """Bind Minecraft metadata semantics over an injected Artifact acquisition port."""

    return MinecraftServerArtifactAssembly(
        provider=OfficialMinecraftServerArtifactProvider(
            acquisition,
            metadata_opener=metadata_opener,
        )
    )


__all__ = [
    "MinecraftServerArtifactAssembly",
    "compose_official_minecraft_server_artifacts",
]
