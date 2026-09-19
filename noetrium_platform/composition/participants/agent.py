from __future__ import annotations

import hashlib

from noetrium_platform.capabilities.participant.agent.api import AgentIdentity, AgentSnapshot
from noetrium_platform.capabilities.participant.core.api.contracts import ParticipantImplementationIdentity
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantResolverPort, ParticipantRuntimeEndpoint
from noetrium_platform.capabilities.participant.core.api.lifecycle import ParticipantIdentityMismatch, ParticipantLifecycleAdapter

from .base import PolicyParticipantAdapter


class AgentParticipantPolicy:
    kind = "agent"

    @staticmethod
    def _plugin(plugin: object) -> ParticipantRuntimeEndpoint:
        if not isinstance(plugin, ParticipantRuntimeEndpoint):
            raise TypeError("agent participant plugin does not satisfy ParticipantRuntimeEndpoint")
        return plugin

    @classmethod
    def _identity(cls, plugin: object) -> AgentIdentity:
        identity = getattr(cls._plugin(plugin), "identity", None)
        if not isinstance(identity, AgentIdentity):
            raise TypeError("agent participant implementation exposes the wrong domain identity")
        return identity

    def implementation_identity(self, plugin: object) -> ParticipantImplementationIdentity:
        i = self._identity(plugin)
        return ParticipantImplementationIdentity(
            self.kind, i.agent_id, i.implementation_version, i.abi_version, i.schema_version, i.artifact_digest or None
        )

    def open_session(self, plugin: object, *, session_id: str, services: object) -> object:
        return self._plugin(plugin).open_session(session_id=session_id, services=services)

    def checkpoint(self, plugin: object, session: object, *, session_id: str) -> bytes:
        snapshot = session.checkpoint()
        if not isinstance(snapshot, AgentSnapshot):
            raise TypeError("AgentSession.checkpoint must return AgentSnapshot")
        identity = self._identity(plugin)
        expected = (identity.agent_id, identity.implementation_version, identity.schema_version, session_id)
        actual = (snapshot.agent_id, snapshot.implementation_version, snapshot.schema_version, snapshot.session_id)
        if actual != expected or hashlib.sha256(snapshot.opaque_payload).hexdigest() != snapshot.payload_sha256:
            raise ParticipantIdentityMismatch("Agent snapshot identity/checksum mismatch")
        return snapshot.opaque_payload

    def restore(self, plugin: object, session: object, payload: bytes, *, session_id: str) -> None:
        identity = self._identity(plugin)
        session.restore(AgentSnapshot(
            identity.agent_id,
            identity.implementation_version,
            identity.schema_version,
            session_id,
            hashlib.sha256(payload).hexdigest(),
            payload,
        ))


def agent_participant_adapter(resolver: ParticipantResolverPort) -> ParticipantLifecycleAdapter:
    return PolicyParticipantAdapter(resolver, AgentParticipantPolicy())


__all__ = ["AgentParticipantPolicy", "agent_participant_adapter"]
