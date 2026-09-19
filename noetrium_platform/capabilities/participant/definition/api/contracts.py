from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from noetrium_platform.capabilities.participant.core.api.contracts import (
    ParticipantConfigurationArtifact,
    ParticipantImplementationIdentity,
)

ParticipantImplementationFactory = Callable[[ParticipantConfigurationArtifact], object]


@dataclass(frozen=True, slots=True)
class RegisteredParticipantImplementation:
    identity: ParticipantImplementationIdentity
    factory: ParticipantImplementationFactory


__all__ = [
    "ParticipantImplementationFactory",
    "RegisteredParticipantImplementation",
]
