from __future__ import annotations

from collections.abc import Callable
import hashlib

from noetrium_platform.capabilities.participant.agent.api import AgentSnapshot
from noetrium_platform.capabilities.participant.method.api import MethodSnapshot
from noetrium_platform.foundation.kernel.structure import NoetriumUnit

from noetrium_platform.capabilities.participant.core.api import (
    ParticipantIdentityMismatch,
    ParticipantResolverPort,
    ParticipantRuntimeEndpoint,
)

from noetrium_platform.capabilities.participant.core.api import (
    participant_implementation_artifact,
    participant_implementation_id,
    participant_implementation_kind,
    participant_implementation_schema,
    participant_implementation_version,
    require_participant_implementation,
)

from .base import PolicyParticipantAdapter

IdentityResolver = Callable[[ParticipantRuntimeEndpoint], NoetriumUnit]
CheckpointEncoder = Callable[[ParticipantRuntimeEndpoint, object, str], bytes]
CheckpointRestorer = Callable[[ParticipantRuntimeEndpoint, object, bytes, str], None]


class RuntimeParticipantPolicy:
    """Single participant lifecycle policy; domains provide typed codecs, not machines."""

    def __init__(
        self,
        kind: str,
        *,
        identity: IdentityResolver | None = None,
        checkpoint: CheckpointEncoder | None = None,
        restore: CheckpointRestorer | None = None,
    ) -> None:
        if type(kind) is not str or not kind.strip():
            raise ValueError("participant policy kind is required")
        self.kind = kind
        self._identity = identity or self._default_identity
        self._checkpoint = checkpoint or self._default_checkpoint
        self._restore = restore or self._default_restore

    @staticmethod
    def _plugin(plugin: object) -> ParticipantRuntimeEndpoint:
        if not isinstance(plugin, ParticipantRuntimeEndpoint):
            raise TypeError("participant plugin does not satisfy ParticipantRuntimeEndpoint")
        return plugin

    @staticmethod
    def _default_identity(plugin: ParticipantRuntimeEndpoint) -> NoetriumUnit:
        return plugin.implementation_identity

    @staticmethod
    def _default_checkpoint(
        plugin: ParticipantRuntimeEndpoint,
        session: object,
        session_id: str,
    ) -> bytes:
        del plugin, session_id
        payload = session.checkpoint()
        if not isinstance(payload, bytes):
            raise TypeError("participant session checkpoint must return bytes")
        return payload
    @staticmethod
    def _default_restore(
        plugin: ParticipantRuntimeEndpoint,
        session: object,
        payload: bytes,
        session_id: str,
    ) -> None:
        del plugin, session_id
        session.restore(payload)

    def implementation_identity(self, plugin: object) -> NoetriumUnit:
        identity = self._identity(self._plugin(plugin))
        require_participant_implementation(identity)
        if participant_implementation_kind(identity) != self.kind:
            raise ParticipantIdentityMismatch(
                f"runtime participant kind mismatch: requested={self.kind} actual={participant_implementation_kind(identity)}"
            )
        return identity

    def open_session(self, plugin: object, *, session_id: str, services: object) -> object:
        return self._plugin(plugin).open_session(session_id=session_id, services=services)

    def checkpoint(self, plugin: object, session: object, *, session_id: str) -> bytes:
        payload = self._checkpoint(self._plugin(plugin), session, session_id)
        if not isinstance(payload, bytes):
            raise TypeError("participant checkpoint codec must return bytes")
        return payload

    def restore(self, plugin: object, session: object, payload: bytes, *, session_id: str) -> None:
        self._restore(self._plugin(plugin), session, payload, session_id)

def generic_participant_adapter(
    kind: str,
    resolver: ParticipantResolverPort,
) -> PolicyParticipantAdapter:
    return PolicyParticipantAdapter(resolver, RuntimeParticipantPolicy(kind))



def _agent_checkpoint(plugin: ParticipantRuntimeEndpoint, session: object, session_id: str) -> bytes:
    snapshot = session.checkpoint()
    if not isinstance(snapshot, AgentSnapshot):
        raise TypeError('AgentSession.checkpoint must return AgentSnapshot')
    identity = require_participant_implementation(plugin.implementation_identity)
    expected = (participant_implementation_id(identity), participant_implementation_version(identity), participant_implementation_schema(identity), session_id)
    actual = (snapshot.agent_id, snapshot.implementation_version, snapshot.schema_version, snapshot.session_id)
    if actual != expected or hashlib.sha256(snapshot.opaque_payload).hexdigest() != snapshot.payload_sha256:
        raise ParticipantIdentityMismatch('Agent snapshot identity/checksum mismatch')
    return snapshot.opaque_payload


def _agent_restore(plugin: ParticipantRuntimeEndpoint, session: object, payload: bytes, session_id: str) -> None:
    identity = require_participant_implementation(plugin.implementation_identity)
    session.restore(AgentSnapshot(participant_implementation_id(identity), participant_implementation_version(identity), participant_implementation_schema(identity), session_id, hashlib.sha256(payload).hexdigest(), payload))


def agent_participant_adapter(resolver: ParticipantResolverPort) -> PolicyParticipantAdapter:
    return PolicyParticipantAdapter(resolver, RuntimeParticipantPolicy('agent', checkpoint=_agent_checkpoint, restore=_agent_restore))


def capability_participant_adapter(resolver: ParticipantResolverPort) -> PolicyParticipantAdapter:
    return PolicyParticipantAdapter(resolver, RuntimeParticipantPolicy('capability_provider'))


def environment_participant_adapter(resolver: ParticipantResolverPort) -> PolicyParticipantAdapter:
    return PolicyParticipantAdapter(resolver, RuntimeParticipantPolicy('environment'))


def _method_checkpoint(plugin: ParticipantRuntimeEndpoint, session: object, session_id: str) -> bytes:
    snapshot = session.checkpoint()
    if not isinstance(snapshot, MethodSnapshot):
        raise TypeError('MethodSession.checkpoint must return MethodSnapshot')
    identity = require_participant_implementation(plugin.implementation_identity)
    expected = (participant_implementation_id(identity), participant_implementation_version(identity), participant_implementation_schema(identity), participant_implementation_artifact(identity), session_id)
    actual = (snapshot.method_id, snapshot.implementation_version, snapshot.schema_version, snapshot.method_runtime_binding_digest or None, snapshot.session_id)
    if actual != expected or hashlib.sha256(snapshot.opaque_payload).hexdigest() != snapshot.payload_sha256:
        raise ParticipantIdentityMismatch('Method snapshot identity/checksum mismatch')
    return snapshot.opaque_payload


def _method_restore(plugin: ParticipantRuntimeEndpoint, session: object, payload: bytes, session_id: str) -> None:
    identity = require_participant_implementation(plugin.implementation_identity)
    session.restore(MethodSnapshot(participant_implementation_id(identity), participant_implementation_version(identity), participant_implementation_schema(identity), participant_implementation_artifact(identity), session_id, hashlib.sha256(payload).hexdigest(), payload))


def method_participant_adapter(resolver: ParticipantResolverPort) -> PolicyParticipantAdapter:
    return PolicyParticipantAdapter(resolver, RuntimeParticipantPolicy('method', checkpoint=_method_checkpoint, restore=_method_restore))


__all__ = [
    "CheckpointEncoder",
    "CheckpointRestorer",
    "IdentityResolver",
    "RuntimeParticipantPolicy",
    "generic_participant_adapter",
    "agent_participant_adapter",
    "capability_participant_adapter",
    "environment_participant_adapter",
    "method_participant_adapter",
]
