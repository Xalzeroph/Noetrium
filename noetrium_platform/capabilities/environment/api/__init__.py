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
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.foundation.kernel.kernel.operation import EffectClass, EffectCertainty, EffectReceipt
from .conformance import (
    EnvironmentConformanceProbe,
    EnvironmentProviderConformanceReceipt,
    verify_environment_provider_conformance,
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
    EnvironmentActionLifecycle,
    EnvironmentActionPhase,
    EnvironmentCapabilityDescriptor,
    EnvironmentCoordinationPort,
    EnvironmentCoordinationReceipt,
    EnvironmentCoordinationRequest,
    EnvironmentQuery,
    EnvironmentQueryKind,
    EnvironmentQueryPort,
    EnvironmentQueryResult,
    EnvironmentRawEventReceipt,
    EnvironmentRawEventRecord,
    EnvironmentRawRecordSinkPort,
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
    "verify_environment_provider_conformance",
    "EnvironmentDiagnosticsPort", "EnvironmentProviderCapabilities",
    "EnvironmentProviderPort", "EnvironmentSessionDiagnostics",
    "EnvironmentSessionServices",
    "EnvironmentActionLifecycle", "EnvironmentActionPhase",
    "EnvironmentCapabilityDescriptor",
    "EnvironmentCoordinationPort", "EnvironmentCoordinationReceipt",
    "EnvironmentCoordinationRequest",
    "EnvironmentQuery", "EnvironmentQueryKind", "EnvironmentQueryPort",
    "EnvironmentQueryResult",
    "EnvironmentRawEventReceipt", "EnvironmentRawEventRecord",
    "EnvironmentRawRecordSinkPort",
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
    EnvironmentProfileReferenceSummary,
    EnvironmentProfileRevision,
    EnvironmentProfileUseIntent,
    EnvironmentSpec,
    ExecutionEnvironmentCatalogPort,
    ExecutionEnvironmentKind,
)
from noetrium_platform.capabilities.environment.embodied.api import (
    ActionKind,
    ActionSpec,
    EmbodiedActionCommand,
    EmbodiedCaptureReceipt,
    EmbodiedEvent,
    EmbodiedEventKind,
    EmbodimentKind,
    EmbodimentSpec,
    EpisodeSpec,
    SensorModality,
    SensorSpec,
)

_ENVIRONMENT_AUTHORING_EXPORTS = (
    "ActionKind",
    "ActionSpec",
    "EmbodiedActionCommand",
    "EmbodiedCaptureReceipt",
    "EmbodiedEvent",
    "EmbodiedEventKind",
    "EmbodimentKind",
    "EmbodimentSpec",
    "EnvironmentCleanlinessKind",
    "EnvironmentCleanlinessProof",
    "EnvironmentInstance",
    "EnvironmentInstanceAcquisition",
    "EnvironmentInstanceState",
    "EnvironmentProfileGcAssessment",
    "EnvironmentProfileLifecycle",
    "EnvironmentProfileReferenceSummary",
    "EnvironmentProfileRevision",
    "EnvironmentProfileUseIntent",
    "EnvironmentSpec",
    "EpisodeSpec",
    "ExecutionEnvironmentCatalogPort",
    "ExecutionEnvironmentKind",
    "SensorModality",
    "SensorSpec",
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
