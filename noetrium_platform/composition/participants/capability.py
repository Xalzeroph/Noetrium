from __future__ import annotations

from noetrium_platform.capabilities.participant.capability.api import CapabilityProviderIdentity
from noetrium_platform.capabilities.participant.core.api import (
    ParticipantImplementationIdentity,
    ParticipantResolverPort,
    ParticipantRuntimeEndpoint,
)

from .base import PolicyParticipantAdapter
from .generic import RuntimeParticipantPolicy


def _identity(plugin: ParticipantRuntimeEndpoint) -> ParticipantImplementationIdentity:
    identity = getattr(plugin, "identity", None)
    if not isinstance(identity, CapabilityProviderIdentity):
        raise TypeError("capability provider participant implementation exposes the wrong domain identity")
    return ParticipantImplementationIdentity(
        "capability_provider",
        identity.provider_id,
        identity.implementation_version,
        identity.abi_version,
        identity.schema_version,
        identity.artifact_digest or None,
    )
def capability_participant_adapter(resolver: ParticipantResolverPort) -> PolicyParticipantAdapter:
    return PolicyParticipantAdapter(
        resolver,
        RuntimeParticipantPolicy("capability_provider", identity=_identity),
    )


__all__ = ["capability_participant_adapter"]
