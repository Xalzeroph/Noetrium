"""Execution-facing participant contracts.

This is the only participant surface visible above Execution. It deliberately
projects the subset of Participant contracts required to bind, checkpoint,
resolve and execute participants inside research execution.
"""

from noetrium_platform.capabilities.api import (
    BoundParticipant,
    BoundParticipants,
    CapabilityDescriptor,
    CapabilityPort,
    CapabilityRequest,
    CapabilityResult,
    ParticipantCheckpoint,
    ParticipantCheckpointOperationsPort,
    ParticipantCheckpointRef,
    ParticipantImplementationIdentity,
    ParticipantResolutionPort,
    ParticipantRuntimeBinding,
    ParticipantSessionBinding,
    ParticipantSessionLifecyclePort,
    ParticipantSessionRuntimeIdentity,
    ProjectParticipantBinding,
    capability_request_digest,
)

__all__ = [
    "BoundParticipant",
    "BoundParticipants",
    "CapabilityDescriptor",
    "CapabilityPort",
    "CapabilityRequest",
    "CapabilityResult",
    "ParticipantCheckpoint",
    "ParticipantCheckpointOperationsPort",
    "ParticipantCheckpointRef",
    "ParticipantImplementationIdentity",
    "ParticipantResolutionPort",
    "ParticipantRuntimeBinding",
    "ParticipantSessionBinding",
    "ParticipantSessionLifecyclePort",
    "ParticipantSessionRuntimeIdentity",
    "ProjectParticipantBinding",
    "capability_request_digest",
]
