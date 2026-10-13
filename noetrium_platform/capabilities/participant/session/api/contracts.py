from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from noetrium_platform.capabilities.participant.core.api import ParticipantSessionRuntimeIdentity
from noetrium_platform.capabilities.participant.core.api import ParticipantSessionRuntime

ParticipantSessionRuntimeFactory = Callable[[], ParticipantSessionRuntime]


@dataclass(frozen=True, slots=True)
class RegisteredParticipantSessionRuntime:
    identity: ParticipantSessionRuntimeIdentity
    factory: ParticipantSessionRuntimeFactory


__all__ = ["ParticipantSessionRuntimeFactory", "RegisteredParticipantSessionRuntime"]
