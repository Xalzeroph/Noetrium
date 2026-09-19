from __future__ import annotations

from noetrium_platform.capabilities.participant.capability.api import CapabilityProviderIdentity
from noetrium_platform.capabilities.participant.core.api.contracts import ParticipantImplementationIdentity
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantResolverPort, ParticipantRuntimeEndpoint
from noetrium_platform.capabilities.participant.core.api.lifecycle import ParticipantLifecycleAdapter

from .base import PolicyParticipantAdapter


class CapabilityProviderParticipantPolicy:
    kind = "capability_provider"

    @staticmethod
    def _plugin(plugin: object) -> ParticipantRuntimeEndpoint:
        if not isinstance(plugin, ParticipantRuntimeEndpoint):
            raise TypeError("capability provider participant plugin does not satisfy ParticipantRuntimeEndpoint")
        return plugin

    @classmethod
    def _identity(cls, plugin: object) -> CapabilityProviderIdentity:
        identity = getattr(cls._plugin(plugin), "identity", None)
        if not isinstance(identity, CapabilityProviderIdentity):
            raise TypeError("capability provider participant implementation exposes the wrong domain identity")
        return identity

    def implementation_identity(self, plugin: object) -> ParticipantImplementationIdentity:
        i = self._identity(plugin)
        return ParticipantImplementationIdentity(
            self.kind, i.provider_id, i.implementation_version, i.abi_version, i.schema_version, i.artifact_digest or None
        )

    def open_session(self, plugin: object, *, session_id: str, services: object) -> object:
        return self._plugin(plugin).open_session(session_id=session_id, services=services)

    def checkpoint(self, plugin: object, session: object, *, session_id: str) -> bytes:
        del plugin, session_id
        payload = session.checkpoint()
        if not isinstance(payload, bytes):
            raise TypeError("CapabilityProviderSession.checkpoint must return bytes")
        return payload

    def restore(self, plugin: object, session: object, payload: bytes, *, session_id: str) -> None:
        del plugin, session_id
        session.restore(payload)


def capability_participant_adapter(resolver: ParticipantResolverPort) -> ParticipantLifecycleAdapter:
    return PolicyParticipantAdapter(resolver, CapabilityProviderParticipantPolicy())


__all__ = ["CapabilityProviderParticipantPolicy", "capability_participant_adapter"]
