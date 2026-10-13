from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from noetrium_platform.foundation.kernel.structure import NoetriumUnit

from noetrium_platform.capabilities.participant.core.api import (
    ParticipantConfigurationArtifact,
)

ParticipantImplementationFactory = Callable[[ParticipantConfigurationArtifact], object]


@dataclass(frozen=True, slots=True)
class RegisteredParticipantImplementation:
    identity: NoetriumUnit
    factory: ParticipantImplementationFactory


__all__ = [
    "ParticipantImplementationFactory",
    "RegisteredParticipantImplementation",
]
