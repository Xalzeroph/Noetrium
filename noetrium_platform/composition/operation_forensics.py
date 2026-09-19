from __future__ import annotations

from noetrium_platform.evidence.data.state.api import StateVersionConflict

from noetrium_platform.infrastructure.reliability.effect.api import PendingEffectRecoveryRequired
from noetrium_platform.infrastructure.reliability.failure.api import (
    DEFAULT_FAILURE_CATALOG,
    ClassifiedOperationFailure,
    FailureCatalog,
    OperationFailureReferenceProjection,
    OperationFailureReferenceProjector,
    PartialOperationFailureClassifier,
)
from noetrium_platform.infrastructure.reliability.forensics.runtime import FailureRecorder
from noetrium_platform.infrastructure.reliability.forensics.composition import ForensicStore
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, OperationAuxiliaryFailure, OperationRequest, OperationSemanticPolicyViolation
from noetrium_platform.foundation.kernel.kernel.failure_materialization import FailureRecordReceipt
from noetrium_platform.capabilities.participant.core.api.runtime_operations import participant_operation_verb


class CoreOperationFailureClassifier:
    """Classifies only domain-agnostic kernel/state/effect-journal failures."""

    def __init__(self, catalog: FailureCatalog = DEFAULT_FAILURE_CATALOG) -> None:
        self.catalog = catalog

    def classify(
        self,
        request: OperationRequest[object],
        exc: BaseException,
    ) -> ClassifiedOperationFailure | None:
        if isinstance(exc, StateVersionConflict):
            return ClassifiedOperationFailure(self.catalog.require("STATE", "VERSION_CONFLICT", "commit"))
        if isinstance(exc, OperationSemanticPolicyViolation):
            return ClassifiedOperationFailure(
                self.catalog.require("PLATFORM", "OPERATION_SEMANTIC_POLICY_VIOLATION", "operation_policy")
            )
        operation = request.operation_type
        if participant_operation_verb(operation) == "resolve":
            return ClassifiedOperationFailure(
                self.catalog.require("PARTICIPANT", "RESOLUTION_FAILURE", "resolve")
            )
        if operation == "effect.intent.pending_check" and isinstance(exc, PendingEffectRecoveryRequired):
            return ClassifiedOperationFailure(
                self.catalog.require("PLATFORM", "PENDING_EFFECT_RECOVERY_REQUIRED", "pending_effect_guard"),
                EffectCertainty.EFFECT_UNKNOWN.value,
            )
        if operation == "effect.intent.prepare":
            return ClassifiedOperationFailure(
                self.catalog.require("PLATFORM", "EFFECT_INTENT_PREPARE_FAILURE", "effect_journal_prepare")
            )
        if operation in {"effect.intent.result_record", "effect.intent.reconciled"}:
            return ClassifiedOperationFailure(
                self.catalog.require("PLATFORM", "EFFECT_INTENT_POST_EFFECT_RECORD_FAILURE", "effect_journal_post_effect"),
                EffectCertainty.EFFECT_UNKNOWN.value,
            )
        if operation in {"effect.intent.consumed", "effect.intent.not_applied"}:
            return ClassifiedOperationFailure(
                self.catalog.require("PLATFORM", "EFFECT_INTENT_TERMINAL_RECORD_FAILURE", "effect_journal_terminal")
            )
        return None


class OperationFailureClassifierChain:
    def __init__(
        self,
        classifiers: tuple[PartialOperationFailureClassifier, ...],
        *,
        catalog: FailureCatalog = DEFAULT_FAILURE_CATALOG,
    ) -> None:
        self.classifiers = classifiers
        self.catalog = catalog

    def classify(
        self,
        request: OperationRequest[object],
        exc: BaseException,
    ) -> ClassifiedOperationFailure:
        for classifier in self.classifiers:
            classified = classifier.classify(request, exc)
            if classified is not None:
                return classified
        return ClassifiedOperationFailure(
            self.catalog.require("PLATFORM", "OPERATION_FAILURE", "component_boundary")
        )


class OperationForensicFailureSink:
    """Kernel failure sink; domain classification/projectors are injected composition."""

    def __init__(
        self,
        store: ForensicStore,
        *,
        classifier: OperationFailureClassifierChain | None = None,
        reference_projector: OperationFailureReferenceProjector | None = None,
    ) -> None:
        self.recorder = FailureRecorder(store)
        self.classifier = classifier or OperationFailureClassifierChain((CoreOperationFailureClassifier(),))
        self.reference_projector = reference_projector

    def record(self, request: OperationRequest[object], exc: BaseException) -> FailureRecordReceipt:
        classified = self.classifier.classify(request, exc)
        refs = (
            self.reference_projector.project(request, exc)
            if self.reference_projector is not None
            else OperationFailureReferenceProjection()
        )
        outcome = self.recorder.record(
            spec=classified.spec,
            component_id=request.target.component_id,
            context=request.context,
            exc=exc,
            operation_id=request.operation_id,
            operation_invocation_id=request.invocation_id,
            operation_type=request.operation_type,
            operation_payload_digest=request.payload_digest,
            operation_idempotency_key=request.idempotency_key,
            effect_certainty=classified.effect_certainty,
            request_refs=refs.request_refs,
            effect_refs=refs.effect_refs,
            state_refs=refs.state_refs,
            correlation_refs=refs.correlation_refs,
        )
        auxiliary = tuple(
            OperationAuxiliaryFailure(
                subsystem="forensics.failure_recorder",
                stage=row.stage,
                error_type=row.error_type,
                error_digest=row.error_digest,
                message=row.message,
            )
            for row in outcome.degradations
        )
        return FailureRecordReceipt(outcome.failure.failure_id, auxiliary)


__all__ = [
    "CoreOperationFailureClassifier",
    "OperationFailureClassifierChain",
    "OperationForensicFailureSink",
]
