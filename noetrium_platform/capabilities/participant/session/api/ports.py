from __future__ import annotations

from typing import Protocol

from noetrium_platform.capabilities.participant.core.api.contracts import ParticipantSessionRuntimeIdentity
from .contracts import ParticipantSessionRuntimeFactory, RegisteredParticipantSessionRuntime


class ParticipantSessionRuntimeCatalogPort(Protocol):
    def register(self, identity: ParticipantSessionRuntimeIdentity, factory: ParticipantSessionRuntimeFactory) -> None: ...
    def resolve(self, identity: ParticipantSessionRuntimeIdentity) -> RegisteredParticipantSessionRuntime: ...
    def identities(self) -> tuple[ParticipantSessionRuntimeIdentity, ...]: ...


__all__ = ["ParticipantSessionRuntimeCatalogPort"]
