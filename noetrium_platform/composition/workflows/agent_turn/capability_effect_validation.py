from __future__ import annotations

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityEffectReconciliationResult,
    CapabilityRequest,
    CapabilityResult,
    DurablePreparedCapabilitySession,
    capability_effect_request_id,
    capability_request_digest,
)
from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectReconciliationDisposition,
    require_effect_receipt_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import EffectCertainty

from .capability_effect_contracts import (
    CapabilityEffectIdentityConflict,
    UnresolvedCapabilityEffect,
    UnsafeEffectfulCapability,
)


def require_durable_capability_session(session: object) -> DurablePreparedCapabilitySession:
    if not isinstance(session, DurablePreparedCapabilitySession):
        raise UnsafeEffectfulCapability(
            "effectful capability provider must implement DurablePreparedCapabilitySession"
        )
    if getattr(session, "effect_recovery_durability", None) != "crash_durable":
        raise UnsafeEffectfulCapability(
            "effectful capability provider must declare effect_recovery_durability='crash_durable'"
        )
    return session


def require_capability_effect_result(
    result: CapabilityResult,
    *,
    descriptor: CapabilityDescriptor,
    request: CapabilityRequest,
) -> CapabilityResult:
    if not isinstance(result, CapabilityResult):
        raise TypeError("effectful capability provider must return CapabilityResult")
    if result.capability_id != request.capability_id:
        raise CapabilityEffectIdentityConflict("capability result capability_id mismatch")
    if result.effect is None:
        raise CapabilityEffectIdentityConflict("effectful capability result must include EffectReceipt")
    try:
        require_effect_receipt_request_digest(
            result.effect,
            expected_digest=capability_request_digest(request),
            request_id=capability_effect_request_id(request),
            source="capability effect receipt",
        )
    except ValueError as exc:
        raise CapabilityEffectIdentityConflict(str(exc)) from exc
    if result.effect.effect_class is not descriptor.effect_class:
        raise CapabilityEffectIdentityConflict(
            f"capability effect class mismatch: declared={descriptor.effect_class.value} "
            f"actual={result.effect.effect_class.value}"
        )
    return result


def require_capability_reconciliation(
    reconciliation: CapabilityEffectReconciliationResult,
    *,
    descriptor: CapabilityDescriptor,
    request: CapabilityRequest,
) -> CapabilityEffectReconciliationResult:
    if not isinstance(reconciliation, CapabilityEffectReconciliationResult):
        raise TypeError(
            "reconcile_prepared_capability must return CapabilityEffectReconciliationResult"
        )
    if reconciliation.capability_id != request.capability_id:
        raise CapabilityEffectIdentityConflict("capability reconciliation capability_id mismatch")
    if reconciliation.disposition is EffectReconciliationDisposition.UNKNOWN:
        raise UnresolvedCapabilityEffect(
            f"capability effect remains unresolved: {request.capability_id}"
        )
    if reconciliation.result is None:
        raise CapabilityEffectIdentityConflict(
            "resolved capability reconciliation requires CapabilityResult"
        )
    require_capability_effect_result(
        reconciliation.result,
        descriptor=descriptor,
        request=request,
    )
    certainty = reconciliation.result.effect.certainty
    expected = {
        EffectReconciliationDisposition.APPLIED: EffectCertainty.EFFECT_CONFIRMED,
        EffectReconciliationDisposition.REJECTED: EffectCertainty.EFFECT_REJECTED,
        EffectReconciliationDisposition.NOT_APPLIED: EffectCertainty.NO_EFFECT,
    }[reconciliation.disposition]
    if reconciliation.result.effect.verification_required or certainty is not expected:
        raise CapabilityEffectIdentityConflict(
            f"capability reconciliation proof mismatch: disposition={reconciliation.disposition.value} "
            f"certainty={certainty.value}"
        )
    return reconciliation


def capability_effect_disposition(
    result: CapabilityResult,
) -> EffectReconciliationDisposition | None:
    assert result.effect is not None
    if result.effect.verification_required:
        return None
    return {
        EffectCertainty.EFFECT_CONFIRMED: EffectReconciliationDisposition.APPLIED,
        EffectCertainty.EFFECT_REJECTED: EffectReconciliationDisposition.REJECTED,
        EffectCertainty.NO_EFFECT: EffectReconciliationDisposition.NOT_APPLIED,
    }.get(result.effect.certainty)


__all__ = [
    "capability_effect_disposition",
    "require_capability_effect_result",
    "require_capability_reconciliation",
    "require_durable_capability_session",
]
