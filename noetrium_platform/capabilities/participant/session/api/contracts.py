from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from noetrium_platform.capabilities.participant.core.api.contracts import ParticipantSessionRuntimeIdentity
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantSessionRuntime

ParticipantSessionRuntimeFactory = Callable[[], ParticipantSessionRuntime]


@dataclass(frozen=True, slots=True)
class RegisteredParticipantSessionRuntime:
    identity: ParticipantSessionRuntimeIdentity
    factory: ParticipantSessionRuntimeFactory


__all__ = ["ParticipantSessionRuntimeFactory", "RegisteredParticipantSessionRuntime"]
