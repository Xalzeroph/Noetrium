from __future__ import annotations

from noetrium_platform.capabilities.participant.binding.api import (
    ParticipantConfigurationResolverPort,
    ParticipantImplementationResolverPort,
    ParticipantRuntimeEndpointFactory,
    ParticipantSessionRuntimeResolverPort,
)
from noetrium_platform.capabilities.participant.core.api import (
    ParticipantConfigurationArtifact,
    ParticipantRuntimeBinding,
)
from noetrium_platform.capabilities.participant.core.api import ParticipantRuntimeHandle


class LocalParticipantResolver:
    """Binding authority joining definition, session and configuration leaves."""

    def __init__(
        self,
        implementations: ParticipantImplementationResolverPort,
        runtimes: ParticipantSessionRuntimeResolverPort,
        configurations: ParticipantConfigurationResolverPort,
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
