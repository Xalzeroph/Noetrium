from __future__ import annotations

from typing import Callable, Protocol

from noetrium_platform.foundation.kernel.structure import NoetriumUnit

from noetrium_platform.capabilities.participant.core.api import (
    ParticipantConfigurationArtifact,
    ParticipantRuntimeBinding,
    ParticipantSessionRuntimeIdentity,
)
from noetrium_platform.capabilities.participant.core.api import (
    ParticipantRuntimeEndpoint,
    ParticipantRuntimeHandle,
    ParticipantSessionRuntime,
)


class ParticipantImplementationRegistration(Protocol):
    identity: NoetriumUnit
    factory: Callable[[ParticipantConfigurationArtifact], object]


class ParticipantImplementationResolverPort(Protocol):
    def resolve(
        self,
        identity: NoetriumUnit,
    ) -> ParticipantImplementationRegistration: ...


class ParticipantConfigurationResolverPort(Protocol):
    def resolve(self, configuration_digest: str) -> ParticipantConfigurationArtifact: ...


class ParticipantSessionRuntimeRegistration(Protocol):
    identity: ParticipantSessionRuntimeIdentity
    factory: Callable[[], ParticipantSessionRuntime]


class ParticipantSessionRuntimeResolverPort(Protocol):
    def resolve(
        self,
        identity: ParticipantSessionRuntimeIdentity,
    ) -> ParticipantSessionRuntimeRegistration: ...


ParticipantRuntimeEndpointFactory = Callable[
    [NoetriumUnit, ParticipantSessionRuntimeIdentity, object, ParticipantSessionRuntime],
    ParticipantRuntimeEndpoint,
]


class ParticipantBindingResolverPort(Protocol):
    def resolve(self, binding: ParticipantRuntimeBinding) -> ParticipantRuntimeHandle: ...


__all__ = [
    "ParticipantBindingResolverPort",
    "ParticipantConfigurationResolverPort",
    "ParticipantImplementationResolverPort",
    "ParticipantImplementationRegistration",
    "ParticipantRuntimeEndpointFactory",
    "ParticipantSessionRuntimeResolverPort",
    "ParticipantSessionRuntimeRegistration",
]
