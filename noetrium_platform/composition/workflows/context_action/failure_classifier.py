from __future__ import annotations

from noetrium_platform.infrastructure.reliability.effect.api import EffectAlreadyConsumed, EffectRecoveryAnchorMissing
from noetrium_platform.capabilities.environment.runtime.api import ActionNotApplied, ActionSafetyCapabilityMissing, ActionScientificCommitContradiction
from noetrium_platform.infrastructure.reliability.failure.api import (
    ClassifiedOperationFailure,
    DEFAULT_FAILURE_CATALOG,
    FailureCatalog,
)
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, OperationRequest
from noetrium_platform.capabilities.participant.method.api import MethodObservationDeliveryError, TaskCompletionSafetyCapabilityMissing


class ContextActionFailureClassifier:
    """Failure taxonomy owned by the ContextAction workflow family."""

    def __init__(self, catalog: FailureCatalog = DEFAULT_FAILURE_CATALOG) -> None:
        self.catalog = catalog

    def classify(self, request: OperationRequest[object], exc: BaseException) -> ClassifiedOperationFailure | None:
        if isinstance(exc, MethodObservationDeliveryError):
            return ClassifiedOperationFailure(self.catalog.require("METHOD", "OBSERVATION_DELIVERY", "post_commit_observability"))

        op = request.operation_type
        mapping = {
            "method.open_session": ("METHOD", "SESSION_OPEN_FAILURE", "session_open"),
            "method.close": ("METHOD", "SESSION_CLOSE_FAILURE", "session_close"),
            "environment.open_session": ("ENVIRONMENT", "SESSION_OPEN_FAILURE", "session_open"),
            "environment.close": ("ENVIRONMENT", "SESSION_CLOSE_FAILURE", "session_close"),
            "method.recall": ("METHOD", "SERVING_FAILURE", "recall"),
            "method.ingest": ("METHOD", "INGEST_FAILURE", "ingest"),
            "environment.observe": ("ENVIRONMENT", "OBSERVE_FAILURE", "observe"),
            "environment.action_recovery.prepare": ("ENVIRONMENT", "ACTION_RECOVERY_PREPARATION_FAILURE", "recovery_prepare"),
            "method.task_completion_reconcile": ("METHOD", "TASK_COMPLETION_RECONCILIATION_FAILURE", "completion_reconcile"),
        }
        if op in mapping:
            domain, code, phase = mapping[op]
            return ClassifiedOperationFailure(self.catalog.require(domain, code, phase))
        if op == "method.task_completed":
            if bool(getattr(exc, "task_completion_committed", False)) and bool(getattr(exc, "evolution_uncertain", False)):
                return ClassifiedOperationFailure(self.catalog.require("METHOD", "EVOLUTION_POST_COMMIT_UNCERTAIN", "evolution_post_commit"))
            return ClassifiedOperationFailure(self.catalog.require("METHOD", "EVOLUTION_FAILURE", "evolution"))
        if op == "environment.action_safety_preflight" and isinstance(exc, ActionSafetyCapabilityMissing):
            return ClassifiedOperationFailure(self.catalog.require("ENVIRONMENT", "ACTION_SAFETY_CAPABILITY_MISSING", "preflight"))
        if op == "method.task_completion_safety_preflight" and isinstance(exc, TaskCompletionSafetyCapabilityMissing):
            return ClassifiedOperationFailure(self.catalog.require("METHOD", "TASK_COMPLETION_IDEMPOTENCY_MISSING", "preflight"))
        if op in {"environment.act", "environment.act_prepared"}:
            return ClassifiedOperationFailure(self.catalog.require("ENVIRONMENT", "EFFECT_UNKNOWN", "act"), EffectCertainty.EFFECT_UNKNOWN.value)
        if op in {"environment.reconcile", "environment.reconcile_prepared_action"}:
            return ClassifiedOperationFailure(self.catalog.require("ENVIRONMENT", "EFFECT_RECONCILIATION_FAILURE", "reconcile"), EffectCertainty.EFFECT_UNKNOWN.value)
        if op == "environment.action_commit_consistency" and isinstance(exc, ActionScientificCommitContradiction):
            return ClassifiedOperationFailure(self.catalog.require("PLATFORM", "CROSS_COMPONENT_COMMIT_CONTRADICTION", "commit_consistency"))
        if op == "environment.action_recovery_decision":
            if isinstance(exc, ActionNotApplied):
                return ClassifiedOperationFailure(self.catalog.require("ENVIRONMENT", "ACTION_NOT_APPLIED", "recovery_decision"), EffectCertainty.NO_EFFECT.value)
            return ClassifiedOperationFailure(self.catalog.require("ENVIRONMENT", "EFFECT_RECONCILIATION_FAILURE", "reconcile"), EffectCertainty.EFFECT_UNKNOWN.value)
        if op == "environment.effect.replay_guard":
            if isinstance(exc, EffectAlreadyConsumed):
                return ClassifiedOperationFailure(self.catalog.require("PLATFORM", "EFFECT_ALREADY_CONSUMED", "replay_guard"))
            if isinstance(exc, ActionNotApplied):
                return ClassifiedOperationFailure(self.catalog.require("ENVIRONMENT", "ACTION_NOT_APPLIED", "recovery_decision"), EffectCertainty.NO_EFFECT.value)
        if op == "environment.effect.recovery_anchor_guard" and isinstance(exc, EffectRecoveryAnchorMissing):
            return ClassifiedOperationFailure(self.catalog.require("PLATFORM", "EFFECT_RECOVERY_ANCHOR_MISSING", "recovery_anchor_guard"), EffectCertainty.EFFECT_UNKNOWN.value)
        return None


__all__ = ["ContextActionFailureClassifier"]
