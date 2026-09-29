from __future__ import annotations

import hashlib

from noetrium_platform.capabilities.participant.core.api import (
    ParticipantIdentityMismatch,
    ParticipantImplementationIdentity,
    ParticipantResolverPort,
    ParticipantRuntimeEndpoint,
)
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodSnapshot

from .base import PolicyParticipantAdapter
from .generic import RuntimeParticipantPolicy


def _identity(plugin: ParticipantRuntimeEndpoint) -> ParticipantImplementationIdentity:
    identity = getattr(plugin, "identity", None)
    if not isinstance(identity, MethodIdentity):
        raise TypeError("method participant implementation exposes the wrong domain identity")
    return ParticipantImplementationIdentity(
        "method",
        identity.method_id,
        identity.implementation_version,
        identity.abi_version,
        identity.schema_version,
        identity.artifact_digest or None,
    )


def _checkpoint(plugin: ParticipantRuntimeEndpoint, session: object, session_id: str) -> bytes:
    snapshot = session.checkpoint()
    if not isinstance(snapshot, MethodSnapshot):
        raise TypeError("MethodSession.checkpoint must return MethodSnapshot")
    identity = getattr(plugin, "identity", None)
    if not isinstance(identity, MethodIdentity):
        raise TypeError("method participant implementation exposes the wrong domain identity")
    expected = (
        identity.method_id,
        identity.implementation_version,
        identity.schema_version,
        identity.artifact_digest or None,
        session_id,
    )
    actual = (
        snapshot.method_id,
        snapshot.implementation_version,
        snapshot.schema_version,
        snapshot.method_runtime_binding_digest or None,
        snapshot.session_id,
    )
    if actual != expected or hashlib.sha256(snapshot.opaque_payload).hexdigest() != snapshot.payload_sha256:
        raise ParticipantIdentityMismatch("Method snapshot identity/checksum mismatch")
    return snapshot.opaque_payload


def _restore(plugin: ParticipantRuntimeEndpoint, session: object, payload: bytes, session_id: str) -> None:
    identity = getattr(plugin, "identity", None)
    if not isinstance(identity, MethodIdentity):
        raise TypeError("method participant implementation exposes the wrong domain identity")
    session.restore(MethodSnapshot(
        identity.method_id,
        identity.implementation_version,
        identity.schema_version,
        identity.artifact_digest or None,
        session_id,
        hashlib.sha256(payload).hexdigest(),
        payload,
    ))


def method_participant_adapter(resolver: ParticipantResolverPort) -> PolicyParticipantAdapter:
    return PolicyParticipantAdapter(
        resolver,
        RuntimeParticipantPolicy(
            "method",
            identity=_identity,
            checkpoint=_checkpoint,
            restore=_restore,
        ),
    )


__all__ = ["method_participant_adapter"]
