from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.evidence.artifact.content.composition import compose_artifact_acquisition
from noetrium_platform.evidence.artifact.content.providers.download import HttpOpener

from ..providers.server_artifact import OfficialMinecraftServerArtifactProvider


@dataclass(frozen=True, slots=True)
class MinecraftServerArtifactAssembly:
    provider: OfficialMinecraftServerArtifactProvider


def compose_official_minecraft_server_artifacts(
    *,
    metadata_opener: HttpOpener | None = None,
    artifact_opener: HttpOpener | None = None,
) -> MinecraftServerArtifactAssembly:
    """Bind official Mojang metadata to the generic verified artifact acquirer."""

    acquisition = compose_artifact_acquisition(opener=artifact_opener)
    return MinecraftServerArtifactAssembly(
        provider=OfficialMinecraftServerArtifactProvider(
            acquisition.acquirer,
            metadata_opener=metadata_opener,
        )
    )


__all__ = [
    "MinecraftServerArtifactAssembly",
    "compose_official_minecraft_server_artifacts",
]
