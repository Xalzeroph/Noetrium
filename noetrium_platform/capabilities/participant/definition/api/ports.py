from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from .contracts import ParticipantImplementationFactory, RegisteredParticipantImplementation


class ParticipantImplementationCatalogPort(Protocol):
    def register(self, identity: NoetriumUnit, factory: ParticipantImplementationFactory) -> None: ...
    def resolve(self, identity: NoetriumUnit) -> RegisteredParticipantImplementation: ...
    def identities(self) -> tuple[NoetriumUnit, ...]: ...


__all__ = ["ParticipantImplementationCatalogPort"]
