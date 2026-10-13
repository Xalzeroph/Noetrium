"""Participant Core bounded-context contract facade.

Only stable contracts and ports are exported. Runtime/provider/composition
implementations remain private to the component.
"""
from __future__ import annotations

from .unit_semantics import (
    PARTICIPANT_IMPLEMENTATION_TRAIT,
    participant_implementation_abi,
    participant_implementation_artifact,
    participant_implementation_digest,
    participant_implementation_id,
    participant_implementation_kind,
    participant_implementation_schema,
    participant_implementation_unit,
    participant_implementation_version,
    require_participant_implementation,
)
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

_PARTICIPANT_IMPLEMENTATION_UNIT_EXPORTS = (
    "PARTICIPANT_IMPLEMENTATION_TRAIT",
    "participant_implementation_abi",
    "participant_implementation_artifact",
    "participant_implementation_digest",
    "participant_implementation_id",
    "participant_implementation_kind",
    "participant_implementation_schema",
    "participant_implementation_unit",
    "participant_implementation_version",
    "require_participant_implementation",
)
__all__ = tuple(__all__) + _PARTICIPANT_IMPLEMENTATION_UNIT_EXPORTS
