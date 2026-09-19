from __future__ import annotations

from noetrium_platform.capabilities.participant.binding.runtime.configuration import ParticipantConfigurationCatalog
from noetrium_platform.capabilities.participant.binding.runtime.local_resolver import LocalParticipantResolver
from noetrium_platform.capabilities.participant.definition.runtime.catalog import ParticipantImplementationCatalog
from noetrium_platform.capabilities.participant.session.runtime.runtime_catalog import ParticipantSessionRuntimeCatalog
from noetrium_platform.capabilities.participant.session.runtime.runtime_endpoint import LocalParticipantRuntimeEndpoint


def build_local_participant_resolver(
    implementations: ParticipantImplementationCatalog,
    runtimes: ParticipantSessionRuntimeCatalog,
    configurations: ParticipantConfigurationCatalog,
) -> LocalParticipantResolver:
    """Bind local leaf authorities to the dependency-inverted resolver port."""

    return LocalParticipantResolver(
        implementations,
        runtimes,
        configurations,
        LocalParticipantRuntimeEndpoint,
    )


__all__ = ["build_local_participant_resolver"]
