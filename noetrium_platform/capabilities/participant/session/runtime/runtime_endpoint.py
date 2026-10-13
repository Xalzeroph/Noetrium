from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import NoetriumUnit

from dataclasses import dataclass

from noetrium_platform.capabilities.participant.core.api import (
    ParticipantSessionRuntimeIdentity,
)
from noetrium_platform.capabilities.participant.core.api import ParticipantSessionRuntime


@dataclass(frozen=True, slots=True)
class LocalParticipantRuntimeEndpoint:
    """Session-owned join of one implementation and one session runtime."""

    implementation_identity: NoetriumUnit
    runtime_identity: ParticipantSessionRuntimeIdentity
    implementation: object
    runtime: ParticipantSessionRuntime

    @property
    def identity(self) -> object:
        try:
            return self.implementation.identity
        except AttributeError as exc:
            raise TypeError("participant implementation does not expose its domain identity") from exc

    def open_session(self, *, session_id: str, services: object) -> object:
        return self.runtime.open_session(
            self.implementation,
            session_id=session_id,
            services=services,
        )


__all__ = ["LocalParticipantRuntimeEndpoint"]
