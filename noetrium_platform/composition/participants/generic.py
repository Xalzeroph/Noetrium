from __future__ import annotations

from collections.abc import Callable

from noetrium_platform.capabilities.participant.core.api import (
    ParticipantIdentityMismatch,
    ParticipantImplementationIdentity,
    ParticipantResolverPort,
    ParticipantRuntimeEndpoint,
)

from .base import PolicyParticipantAdapter

IdentityResolver = Callable[[ParticipantRuntimeEndpoint], ParticipantImplementationIdentity]
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
    def _default_identity(plugin: ParticipantRuntimeEndpoint) -> ParticipantImplementationIdentity:
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

    def implementation_identity(self, plugin: object) -> ParticipantImplementationIdentity:
        identity = self._identity(self._plugin(plugin))
        if identity.kind != self.kind:
            raise ParticipantIdentityMismatch(
                f"runtime participant kind mismatch: requested={self.kind} actual={identity.kind}"
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


__all__ = [
    "CheckpointEncoder",
    "CheckpointRestorer",
    "IdentityResolver",
    "RuntimeParticipantPolicy",
    "generic_participant_adapter",
]
