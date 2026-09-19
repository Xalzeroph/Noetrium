from __future__ import annotations

from noetrium_platform.capabilities.participant.core.api.contracts import ParticipantConfigurationArtifact


class ParticipantConfigurationCatalog:
    """Binding authority for immutable configuration selected by a participant."""

    def __init__(self) -> None:
        self._artifacts: dict[str, ParticipantConfigurationArtifact] = {
            "": ParticipantConfigurationArtifact.empty()
        }

    def register(self, artifact: ParticipantConfigurationArtifact) -> None:
        key = artifact.configuration_digest
        if not key:
            raise ValueError("empty participant configuration is reserved")
        if key in self._artifacts:
            raise ValueError(f"duplicate participant configuration digest: {key}")
        self._artifacts[key] = artifact

    def resolve(self, configuration_digest: str) -> ParticipantConfigurationArtifact:
        try:
            return self._artifacts[configuration_digest]
        except KeyError as exc:
            raise KeyError(
                f"unknown participant configuration digest: {configuration_digest}"
            ) from exc


__all__ = ["ParticipantConfigurationCatalog"]
