from __future__ import annotations

from noetrium_platform.capabilities.participant.core.api.contracts import ParticipantImplementationIdentity
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantResolverPort, ParticipantRuntimeEndpoint
from noetrium_platform.capabilities.participant.core.api.lifecycle import ParticipantIdentityMismatch, ParticipantLifecycleAdapter

from .base import PolicyParticipantAdapter


class RuntimeParticipantPolicy:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    @staticmethod
    def _plugin(plugin: object) -> ParticipantRuntimeEndpoint:
        if not isinstance(plugin, ParticipantRuntimeEndpoint):
            raise TypeError("generic participant plugin does not satisfy ParticipantRuntimeEndpoint")
        return plugin

    def implementation_identity(self, plugin: object) -> ParticipantImplementationIdentity:
        identity = self._plugin(plugin).implementation_identity
        if identity.kind != self.kind:
            raise ParticipantIdentityMismatch(
                f"runtime participant kind mismatch: requested={self.kind} actual={identity.kind}"
            )
        return identity


    def open_session(self, plugin: object, *, session_id: str, services: object) -> object:
        return self._plugin(plugin).open_session(session_id=session_id, services=services)

    def checkpoint(self, plugin: object, session: object, *, session_id: str) -> bytes:
        del plugin, session_id
        payload = session.checkpoint()
        if not isinstance(payload, bytes):
            raise TypeError("generic participant session checkpoint must return bytes")
        return payload

    def restore(self, plugin: object, session: object, payload: bytes, *, session_id: str) -> None:
        del plugin, session_id
        session.restore(payload)


def generic_participant_adapter(kind: str, resolver: ParticipantResolverPort) -> ParticipantLifecycleAdapter:
    return PolicyParticipantAdapter(resolver, RuntimeParticipantPolicy(kind))


__all__ = ["RuntimeParticipantPolicy", "generic_participant_adapter"]
