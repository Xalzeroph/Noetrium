from .topology_semantics import (
    PARTICIPANT_COMMUNICATION_RELATION,
    PARTICIPANT_DEPENDENCY_RELATION,
    PARTICIPANT_FEEDBACK_RELATION,
    PARTICIPANT_GRAPH_TRAIT,
    PARTICIPANT_SHARED_STATE_RELATION,
    PARTICIPANT_SUPERVISION_RELATION,
    PARTICIPANT_VERTEX_TRAIT,
    participant_communication,
    participant_coordination_components,
    participant_dependency,
    participant_graph,
    participant_relation,
    participant_roles,
    participant_waves,
    validate_participant_graph,
)
from .unit_semantics import (
    PARTICIPANT_REQUIREMENT_TRAIT,
    participant_requirement,
    participant_requirement_capabilities,
    participant_requirement_configurations,
    participant_requirement_kind,
    participant_requirement_method_id,
    participant_requirement_role,
    participant_requirement_treatment_id,
    require_participant_requirement,
)
from .messaging import (
    PARTICIPANT_MESSAGE_ROUTE_SCHEMA,
    ParticipantMessageFactBinding,
    ParticipantMessageKind,
    ParticipantMessageRecipientReceipt,
    ParticipantMessageRouteReceipt,
    ParticipantMessageRouteRequest,
    ParticipantMessageRouterPort,
    participant_message_content_digest,
)
from .project import (
    ParticipantBindingDiagnostic,
    ParticipantBindingDiagnosticCode,
    ParticipantBindingDiagnosticSeverity,
    ParticipantProjectBindingError,
    ParticipantProviderProfile,
    ProjectParticipantBinding,
)


__all__ = [
    'PARTICIPANT_MESSAGE_ROUTE_SCHEMA',
    'ParticipantMessageFactBinding',
    'ParticipantMessageKind',
    'ParticipantMessageRecipientReceipt',
    'ParticipantMessageRouteReceipt',
    'ParticipantMessageRouteRequest',
    'ParticipantMessageRouterPort',
    'participant_message_content_digest',
    'ParticipantBindingDiagnostic',
    'ParticipantBindingDiagnosticCode',
    'ParticipantBindingDiagnosticSeverity',
    'ParticipantProjectBindingError',
    'ParticipantProviderProfile',
    'ProjectParticipantBinding',
    'MethodRuntimeIdentity',
]


# Parent-facing Participant contracts. Higher systems import only this facade.
from noetrium_platform.capabilities.participant.agent.api.cognition import (
    AgentGoal,
    AgentMemoryContext,
    AgentObservation,
    AgentSkillDescription,
    AgentStepReceipt,
)
from noetrium_platform.capabilities.participant.agent.api.cognition_ports import AgentMemoryPort
from noetrium_platform.capabilities.participant.agent.api.model_view import (
    AGENT_ACTION_HISTORY_VIEW_SCHEMA,
    AgentActionHistoryProjectionReceipt,
    project_action_history,
)
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityApprovalPort,
    CapabilityGuardPort,
    CapabilityPostPolicyPort,
    CapabilityDescriptor,
    CapabilityEffectReconciliationResult,
    CapabilityPort,
    CapabilityRequest,
    CapabilityResult,
    CapabilitySelectionReference,
    CapabilitySelectionView,
    GuardDecision,
    GuardVerdict,
    capability_effect_request_id,
    capability_request_digest,
    materialize_capability_selection_view,
)
from noetrium_platform.capabilities.participant.core.api import (
    BoundParticipant,
    BoundParticipants,
    ParticipantCheckpoint,
    ParticipantCheckpointOperationsPort,
    ParticipantCheckpointRef,
    ParticipantCheckpointRuntimePort,
    ParticipantLifecycleAdapterRegistry,
    ParticipantResolutionPort,
    ParticipantRuntimeBinding,
    ParticipantRuntimeHandle,
    ParticipantSessionBinding,
    ParticipantSessionLifecyclePort,
    ParticipantSessionRuntimeIdentity,
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
    participant_operation_type,
    participant_operation_verb,
)
from noetrium_platform.capabilities.participant.method.api import (
    MethodRuntimeIdentity,
)

_PARENT_FACADE_EXPORTS = (
    "AGENT_ACTION_HISTORY_VIEW_SCHEMA",
    "AgentActionHistoryProjectionReceipt",
    "AgentGoal",
    "AgentMemoryContext",
    "AgentMemoryPort",
    "AgentObservation",
    "AgentSkillDescription",
    "AgentStepReceipt",
    "BoundParticipant",
    "BoundParticipants",
    "CapabilityApprovalPort",
    "CapabilityGuardPort",
    "CapabilityPostPolicyPort",
    "CapabilityDescriptor",
    "CapabilityEffectReconciliationResult",
    "CapabilityPort",
    "CapabilityRequest",
    "CapabilityResult",
    "CapabilitySelectionReference",
    "CapabilitySelectionView",
    "GuardVerdict",
    "ParticipantCheckpoint",
    "ParticipantCheckpointRuntimePort",
    "ParticipantLifecycleAdapterRegistry",
    "ParticipantRuntimeBinding",
    "ParticipantRuntimeHandle",
    "ParticipantSessionBinding",
    "capability_effect_request_id",
    "capability_request_digest",
    "materialize_capability_selection_view",
    "participant_operation_type",
    "participant_operation_verb",
    "project_action_history",
)

__all__ = tuple(__all__) + _PARENT_FACADE_EXPORTS


_PARTICIPANT_PARENT_EXTRA_EXPORTS = (
    "ParticipantSessionRuntimeIdentity",
    "AgentTurnResult",
    "AgentSession",
    "ParticipantCheckpointOperationsPort",
    "ParticipantCheckpointRef",
    "ParticipantResolutionPort",
    "ParticipantSessionLifecyclePort",
)

__all__ = tuple(__all__) + _PARTICIPANT_PARENT_EXTRA_EXPORTS

from noetrium_platform.capabilities.participant.capability.api import GuardDecision
__all__ += ("GuardDecision",)


from noetrium_platform.capabilities.participant.agent.api import (
    AgentSession,
    AgentTurnResult,
)


_PARTICIPANT_TOPOLOGY_EXPORTS = (
    "PARTICIPANT_COMMUNICATION_RELATION",
    "PARTICIPANT_DEPENDENCY_RELATION",
    "PARTICIPANT_FEEDBACK_RELATION",
    "PARTICIPANT_GRAPH_TRAIT",
    "PARTICIPANT_SHARED_STATE_RELATION",
    "PARTICIPANT_SUPERVISION_RELATION",
    "PARTICIPANT_VERTEX_TRAIT",
    "participant_communication",
    "participant_coordination_components",
    "participant_dependency",
    "participant_graph",
    "participant_relation",
    "participant_roles",
    "participant_waves",
    "validate_participant_graph",
)
__all__ = tuple(__all__) + _PARTICIPANT_TOPOLOGY_EXPORTS


_PARTICIPANT_REQUIREMENT_EXPORTS = (
    "PARTICIPANT_REQUIREMENT_TRAIT",
    "participant_requirement",
    "participant_requirement_capabilities",
    "participant_requirement_configurations",
    "participant_requirement_kind",
    "participant_requirement_method_id",
    "participant_requirement_role",
    "participant_requirement_treatment_id",
    "require_participant_requirement",
)
__all__ = tuple(__all__) + _PARTICIPANT_REQUIREMENT_EXPORTS

_PARTICIPANT_IMPLEMENTATION_EXPORTS = (
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
__all__ = tuple(__all__) + _PARTICIPANT_IMPLEMENTATION_EXPORTS
