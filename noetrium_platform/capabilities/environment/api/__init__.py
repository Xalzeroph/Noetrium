from __future__ import annotations

from noetrium_platform.capabilities.environment.api.codec import (
    action_result_from_payload,
    action_result_payload,
    effect_receipt_from_payload,
    effect_receipt_payload,
    observation_from_payload,
    observation_payload,
)
from .action_identity import (
    ActionIdentityViolation,
    ActionSemanticIdentity,
    require_action_recovery_handle_identity,
    require_action_result_identity,
    require_effect_receipt_digest,
    require_reconciliation_identity,
    require_recovery_handle_reconciliation_identity,
)
from .errors import (
    ActionNotApplied,
    ActionRecoveryRequired,
    ActionSafetyCapabilityMissing,
    ActionScientificCommitContradiction,
    EnvironmentCapabilityUnsupported,
)
from .branch_state import (
    EnvironmentBranchState,
    EnvironmentBranchStateMismatch,
    EnvironmentBranchStatePort,
)
from .recovery import EnvironmentRecoverySession
from .reset import EnvironmentResetPort
from .contracts import (
    EnvironmentAssignmentIdentity,
    EnvironmentAssignmentIsolationPort,
    EnvironmentAssignmentIsolationReceipt,
    ActionReconciliationDisposition,
    ActionReconciliationResult,
    ActionRequest,
    ActionResult,
    DurablePreparedActionSession,
    EnvironmentIdentity,
    EnvironmentImplementation,
    EnvironmentSession,
    Observation,
    action_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    EffectClass,
    EffectCertainty,
    EffectReceipt,
)
from .conformance import (
    EnvironmentConformanceProbe,
    EnvironmentProviderConformanceReceipt,
    require_environment_provider_identity,
)
from .provider import (
    EnvironmentCapability,
    EnvironmentDiagnosticsPort,
    EnvironmentProviderCapabilities,
    EnvironmentProviderPort,
    EnvironmentSessionDiagnostics,
    EnvironmentSessionServices,
)
from .interaction import (
    EnvironmentCapabilityDescriptor,
    EnvironmentCoordinationPort,
    EnvironmentCoordinationReceipt,
    EnvironmentCoordinationRequest,
    EnvironmentQuery,
    EnvironmentQueryKind,
    EnvironmentQueryPort,
    EnvironmentQueryResult,
)
from .state_machine import (
    JsonScalar,
    JsonInput,
    JsonMutableValue,
    JsonValue,
    StateMachineDynamicsIdentity,
    StateMachineDynamicsPort,
    StateMachineEnvironmentSpec,
    StateTransition,
    freeze_json_mapping,
    thaw_json,
    thaw_json_mapping,
)

__all__ = [
    "observation_payload",
    "observation_from_payload",
    "effect_receipt_payload",
    "effect_receipt_from_payload",
    "action_result_payload",
    "action_result_from_payload",
"ExecutionContext",
    "EffectClass", "EffectCertainty", "EffectReceipt",
    "ActionIdentityViolation", "ActionNotApplied", "ActionRecoveryRequired",
    "ActionReconciliationDisposition", "ActionReconciliationResult",
    "ActionRequest", "ActionResult", "ActionSafetyCapabilityMissing",
    "ActionScientificCommitContradiction", "ActionSemanticIdentity",
    "EnvironmentBranchState", "EnvironmentBranchStateMismatch",
    "EnvironmentBranchStatePort", "EnvironmentRecoverySession", "EnvironmentResetPort",
    "EnvironmentAssignmentIdentity",
    "EnvironmentAssignmentIsolationPort",
    "EnvironmentAssignmentIsolationReceipt",
    "EnvironmentCapabilityUnsupported", "EnvironmentCapability",
    "EnvironmentConformanceProbe", "EnvironmentProviderConformanceReceipt",
    "require_environment_provider_identity",
    "EnvironmentDiagnosticsPort", "EnvironmentProviderCapabilities",
    "EnvironmentProviderPort", "EnvironmentSessionDiagnostics",
    "EnvironmentSessionServices",
    "EnvironmentCapabilityDescriptor",
    "EnvironmentCoordinationPort", "EnvironmentCoordinationReceipt",
    "EnvironmentCoordinationRequest",
    "EnvironmentQuery", "EnvironmentQueryKind", "EnvironmentQueryPort",
    "EnvironmentQueryResult",


    "DurablePreparedActionSession", "EnvironmentIdentity",
    "EnvironmentImplementation", "EnvironmentSession", "Observation",
    "action_request_digest", "require_action_recovery_handle_identity",
    "require_action_result_identity", "require_effect_receipt_digest",
    "require_reconciliation_identity", "require_recovery_handle_reconciliation_identity",
    "JsonScalar", "JsonInput", "JsonMutableValue", "JsonValue",
    "StateMachineDynamicsIdentity", "StateMachineDynamicsPort",
    "StateMachineEnvironmentSpec", "StateTransition",
    "freeze_json_mapping", "thaw_json", "thaw_json_mapping",
]

from noetrium_platform.capabilities.environment.catalog.api import (
    EnvironmentCleanlinessKind,
    EnvironmentCleanlinessProof,
    EnvironmentInstance,
    EnvironmentInstanceAcquisition,
    EnvironmentInstanceState,
    EnvironmentProfileGcAssessment,
    EnvironmentProfileLifecycle,
    EnvironmentProfileMaterialization,
    EnvironmentProfileReferenceSummary,
    EnvironmentProfileRevision,
    ExecutionEnvironmentCatalogPort,
)
from noetrium_platform.capabilities.environment.software.api import (
    SoftwareActionKind,
    SoftwareActionTimeoutError,
    SoftwareWorldPort,
)

from noetrium_platform.capabilities.environment.embodied.api import (
    ActionKind,
    EmbodiedActionCommand,
    EmbodiedCaptureReceipt,
    EmbodiedEventProjection,
    EmbodiedEventProjectionKind,
    EmbodiedSimulatorBackendPort,
    EmbodimentKind,
    SimulatorObservation,
    SimulatorStep,
    SensorModality,
    action_spec_unit,
    embodiment_actions,
    embodiment_digest,
    embodiment_id,
    embodiment_sensors,
    embodiment_unit,
    episode_id,
    episode_unit,
    require_action_spec,
    require_embodiment,
    require_episode,
    require_sensor,
    sensor_unit,
)

_ENVIRONMENT_AUTHORING_EXPORTS = (
    "sensor_unit",
    "require_sensor",
    "require_episode",
    "require_embodiment",
    "require_action_spec",
    "episode_unit",
    "episode_id",
    "embodiment_unit",
    "embodiment_sensors",
    "embodiment_id",
    "embodiment_digest",
    "embodiment_actions",
    "action_spec_unit",
    "ActionKind",
    "EmbodiedActionCommand",
    "EmbodiedCaptureReceipt",
    "EmbodiedEventProjection",
    "EmbodiedEventProjectionKind",
    "EmbodiedSimulatorBackendPort",
    "EmbodimentKind",
    "EnvironmentCleanlinessKind",
    "EnvironmentCleanlinessProof",
    "EnvironmentInstance",
    "EnvironmentInstanceAcquisition",
    "EnvironmentInstanceState",
    "EnvironmentProfileGcAssessment",
    "EnvironmentProfileLifecycle",
    "EnvironmentProfileMaterialization",
    "EnvironmentProfileReferenceSummary",
    "EnvironmentProfileRevision",
    "SimulatorObservation",
    "SimulatorStep",
    "ExecutionEnvironmentCatalogPort",
    "SensorModality",
    "SoftwareActionKind",
    "SoftwareActionTimeoutError",
    "SoftwareWorldPort",
)
__all__ += _ENVIRONMENT_AUTHORING_EXPORTS

from .fork import (
    EnvironmentForkReceipt,
    EnvironmentSessionOpener,
    fork_environment_session,
)
from .replay import (
    EnvironmentReplayError,
    EnvironmentReplayReceipt,
    replay_environment_prefix,
)
__all__ = tuple(__all__) + (
    "EnvironmentForkReceipt",
    "EnvironmentSessionOpener",
    "fork_environment_session",
    "EnvironmentReplayError",
    "EnvironmentReplayReceipt",
    "replay_environment_prefix",
)

from .records import environment_effect_record, environment_observation_record
from .semantics import ENVIRONMENT_CAPABILITY_TRAIT, ENVIRONMENT_TRAIT, environment_capabilities, environment_unit, require_environment_unit
