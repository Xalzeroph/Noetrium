from __future__ import annotations

from typing import Protocol

from noetrium_platform.capabilities.participant.core.api.contracts import ParticipantImplementationIdentity
from .contracts import ParticipantImplementationFactory, RegisteredParticipantImplementation


class ParticipantImplementationCatalogPort(Protocol):
    def register(self, identity: ParticipantImplementationIdentity, factory: ParticipantImplementationFactory) -> None: ...
    def resolve(self, identity: ParticipantImplementationIdentity) -> RegisteredParticipantImplementation: ...
    def identities(self) -> tuple[ParticipantImplementationIdentity, ...]: ...


__all__ = ["ParticipantImplementationCatalogPort"]
