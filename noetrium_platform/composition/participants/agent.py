from __future__ import annotations

import hashlib

from noetrium_platform.capabilities.participant.agent.api import AgentIdentity, AgentSnapshot
from noetrium_platform.capabilities.participant.core.api import (
    ParticipantIdentityMismatch,
    ParticipantImplementationIdentity,
    ParticipantResolverPort,
    ParticipantRuntimeEndpoint,
)

from .base import PolicyParticipantAdapter
from .generic import RuntimeParticipantPolicy


def _identity(plugin: ParticipantRuntimeEndpoint) -> ParticipantImplementationIdentity:
    identity = getattr(plugin, "identity", None)
    if not isinstance(identity, AgentIdentity):
        raise TypeError("agent participant implementation exposes the wrong domain identity")
    return ParticipantImplementationIdentity(
        "agent",
        identity.agent_id,
        identity.implementation_version,
        identity.abi_version,
        identity.schema_version,
        identity.artifact_digest or None,
    )
def _checkpoint(plugin: ParticipantRuntimeEndpoint, session: object, session_id: str) -> bytes:
    snapshot = session.checkpoint()
    if not isinstance(snapshot, AgentSnapshot):
        raise TypeError("AgentSession.checkpoint must return AgentSnapshot")
    identity = getattr(plugin, "identity", None)
    if not isinstance(identity, AgentIdentity):
        raise TypeError("agent participant implementation exposes the wrong domain identity")
    expected = (
        identity.agent_id,
        identity.implementation_version,
        identity.schema_version,
        session_id,
    )
    actual = (
        snapshot.agent_id,
        snapshot.implementation_version,
        snapshot.schema_version,
        snapshot.session_id,
    )
    if actual != expected or hashlib.sha256(snapshot.opaque_payload).hexdigest() != snapshot.payload_sha256:
        raise ParticipantIdentityMismatch("Agent snapshot identity/checksum mismatch")
    return snapshot.opaque_payload


def _restore(plugin: ParticipantRuntimeEndpoint, session: object, payload: bytes, session_id: str) -> None:
    identity = getattr(plugin, "identity", None)
    if not isinstance(identity, AgentIdentity):
        raise TypeError("agent participant implementation exposes the wrong domain identity")
    session.restore(AgentSnapshot(
        identity.agent_id,
        identity.implementation_version,
        identity.schema_version,
        session_id,
        hashlib.sha256(payload).hexdigest(),
        payload,
    ))


def agent_participant_adapter(resolver: ParticipantResolverPort) -> PolicyParticipantAdapter:
    return PolicyParticipantAdapter(
        resolver,
        RuntimeParticipantPolicy(
            "agent",
            identity=_identity,
            checkpoint=_checkpoint,
            restore=_restore,
        ),
    )


__all__ = ["agent_participant_adapter"]
