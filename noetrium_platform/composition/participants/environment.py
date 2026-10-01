from __future__ import annotations

from noetrium_platform.capabilities.environment.api import EnvironmentIdentity
from noetrium_platform.capabilities.participant.core.api import (
    ParticipantImplementationIdentity,
    ParticipantResolverPort,
    ParticipantRuntimeEndpoint,
)

from .base import PolicyParticipantAdapter
from .generic import RuntimeParticipantPolicy


def _identity(plugin: ParticipantRuntimeEndpoint) -> ParticipantImplementationIdentity:
    identity = getattr(plugin, "identity", None)
    if not isinstance(identity, EnvironmentIdentity):
        raise TypeError("environment participant implementation exposes the wrong domain identity")
    return ParticipantImplementationIdentity(
        "environment",
        identity.environment_id,
        identity.implementation_version,
        identity.abi_version,
        identity.schema_version,
        identity.artifact_digest or None,
    )
def environment_participant_adapter(resolver: ParticipantResolverPort) -> PolicyParticipantAdapter:
    return PolicyParticipantAdapter(
        resolver,
        RuntimeParticipantPolicy("environment", identity=_identity),
    )


__all__ = ["environment_participant_adapter"]
