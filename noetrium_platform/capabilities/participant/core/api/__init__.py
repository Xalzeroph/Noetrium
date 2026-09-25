"""Participant Core bounded-context contract facade.

Only stable contracts and ports are exported. Runtime/provider/composition
implementations remain private to the component.
"""

from __future__ import annotations

from .bound import (
    BoundParticipant,
    BoundParticipants,
    ParticipantSessionBinding,
)

from .checkpoint import (
    ParticipantCheckpoint,
    ParticipantCheckpointIdentityMismatch,
    ParticipantCheckpointRef,
)

from .contracts import (
    ParticipantConfigurationArtifact,
    ParticipantImplementationIdentity,
    ParticipantRuntimeBinding,
    ParticipantSessionRuntimeIdentity,
)

from .frozen_manifests import (
    ParticipantImplementationInventory,
    ParticipantRuntimeBindingManifest,
    ParticipantRuntimeInventory,
)

from .lifecycle import (
    ParticipantIdentityMismatch,
    ParticipantLifecycleAdapter,
    ParticipantLifecycleAdapterRegistry,
)

from .runtime import (
    ParticipantResolverPort,
    ParticipantRuntimeEndpoint,
    ParticipantRuntimeHandle,
    ParticipantSessionRuntime,
)

from .runtime_operations import (
    PARTICIPANT_OPERATION_VERBS,
    ParticipantOperationContractError,
    participant_operation_type,
    participant_operation_verb,
    validate_participant_kind,
)

from .runtime_ports import (
    ParticipantCheckpointOperationsPort,
    ParticipantCheckpointRuntimePort,
    ParticipantResolutionPort,
    ParticipantSessionLifecyclePort,
)

__all__ = [
    "BoundParticipant",
    "BoundParticipants",
    "PARTICIPANT_OPERATION_VERBS",
    "ParticipantCheckpoint",
    "ParticipantCheckpointIdentityMismatch",
    "ParticipantCheckpointOperationsPort",
    "ParticipantCheckpointRef",
    "ParticipantCheckpointRuntimePort",
    "ParticipantConfigurationArtifact",
    "ParticipantIdentityMismatch",
    "ParticipantImplementationIdentity",
    "ParticipantImplementationInventory",
    "ParticipantLifecycleAdapter",
    "ParticipantLifecycleAdapterRegistry",
    "ParticipantOperationContractError",
    "ParticipantResolutionPort",
    "ParticipantResolverPort",
    "ParticipantRuntimeBinding",
    "ParticipantRuntimeBindingManifest",
    "ParticipantRuntimeEndpoint",
    "ParticipantRuntimeHandle",
    "ParticipantRuntimeInventory",
    "ParticipantSessionBinding",
    "ParticipantSessionLifecyclePort",
    "ParticipantSessionRuntime",
    "ParticipantSessionRuntimeIdentity",
    "participant_operation_type",
    "participant_operation_verb",
    "validate_participant_kind",
]
