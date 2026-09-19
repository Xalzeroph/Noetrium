from __future__ import annotations

from noetrium_platform.capabilities.participant.binding.api.contracts import (
    ParticipantConfigurationCatalogPort,
    ParticipantImplementationCatalogPort,
    ParticipantRuntimeEndpointFactory,
    ParticipantSessionRuntimeCatalogPort,
)
from noetrium_platform.capabilities.participant.core.api.contracts import (
    ParticipantConfigurationArtifact,
    ParticipantRuntimeBinding,
)
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantRuntimeHandle


class LocalParticipantResolver:
    """Binding authority joining definition, session and configuration leaves."""

    def __init__(
        self,
        implementations: ParticipantImplementationCatalogPort,
        runtimes: ParticipantSessionRuntimeCatalogPort,
        configurations: ParticipantConfigurationCatalogPort,
        endpoint_factory: ParticipantRuntimeEndpointFactory,
    ) -> None:
        self._implementations = implementations
        self._runtimes = runtimes
        self._configurations = configurations
        self._endpoint_factory = endpoint_factory

    def resolve(self, binding: ParticipantRuntimeBinding) -> ParticipantRuntimeHandle:
        registered_implementation = self._implementations.resolve(binding.implementation)
        registered_runtime = self._runtimes.resolve(binding.runtime)
        configuration = (
            ParticipantConfigurationArtifact.empty()
            if binding.configuration_digest is None
            else self._configurations.resolve(binding.configuration_digest)
        )
        implementation = registered_implementation.factory(configuration)
        runtime = registered_runtime.factory()
        if runtime.runtime_identity != binding.runtime:
            raise ValueError("participant session runtime factory identity drift")
        endpoint = self._endpoint_factory(
            binding.implementation,
            binding.runtime,
            implementation,
            runtime,
        )
        return ParticipantRuntimeHandle(binding, endpoint)


__all__ = ["LocalParticipantResolver"]
