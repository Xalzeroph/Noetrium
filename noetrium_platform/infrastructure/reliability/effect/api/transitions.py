from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectReceipt

from .contracts import require_effect_receipt_request_digest
from .journal import (
    EffectCompletionEvidence,
    EffectIntent,
    EffectIntentConflict,
    EffectIntentPhase,
    EffectIntentPrepareResult,
    EffectIntentRecord,
    consumption_digest,
    effect_digest,
)

_RESOLVED = {
    EffectCertainty.NO_EFFECT,
    EffectCertainty.EFFECT_CONFIRMED,
    EffectCertainty.EFFECT_REJECTED,
}
_CONSUMABLE = {
    EffectCertainty.EFFECT_CONFIRMED,
    EffectCertainty.EFFECT_REJECTED,
}


def prepare_transition(
    current: EffectIntentRecord | None,
    intent: EffectIntent,
) -> EffectIntentPrepareResult:
    """Pure idempotent PREPARED transition; storage is deliberately out of scope."""

    if current is None:
        return EffectIntentPrepareResult(EffectIntentRecord(intent, EffectIntentPhase.PREPARED), True)
    if current.intent != intent:
        raise EffectIntentConflict(f"effect intent identity conflict: {intent.intent_id}")
    return EffectIntentPrepareResult(current, False)


def _require_request(current: EffectIntentRecord, request_digest: str) -> None:
    if current.intent.request_digest != request_digest:
        raise EffectIntentConflict(f"effect request digest conflict: {current.intent.intent_id}")


def _require_bound_effect(
    current: EffectIntentRecord,
    request_digest: str,
    effect: EffectReceipt | None,
) -> None:
    if effect is None:
        return
    try:
        require_effect_receipt_request_digest(
            effect,
            expected_digest=request_digest,
            request_id=current.intent.request_id,
            source="effect journal receipt",
        )
    except ValueError as exc:
        raise EffectIntentConflict(
            f"effect receipt request digest conflict: {current.intent.intent_id}"
        ) from exc


def effect_transition(
    current: EffectIntentRecord,
    *,
    request_digest: str,
    phase: EffectIntentPhase,
    effect: EffectReceipt | None,
) -> EffectIntentRecord:
    """Pure RESULT_RECORDED/RECONCILED transition authority."""

    if phase not in {EffectIntentPhase.RESULT_RECORDED, EffectIntentPhase.RECONCILED}:
        raise ValueError(f"unsupported effect transition target: {phase}")
    _require_request(current, request_digest)
    _require_bound_effect(current, request_digest, effect)
    digest = effect_digest(effect)
    intent_id = current.intent.intent_id

    if current.phase is phase:
        if current.effect_digest != digest:
            raise EffectIntentConflict(f"effect digest conflict: {intent_id}")
        return current
    if current.phase is EffectIntentPhase.RECONCILED:
        if current.effect_digest != digest:
            raise EffectIntentConflict(f"reconciled effect conflict: {intent_id}")
        return current
    if phase is EffectIntentPhase.RESULT_RECORDED and current.phase is not EffectIntentPhase.PREPARED:
        raise EffectIntentConflict(f"invalid effect intent transition: {current.phase}->{phase}")
    if phase is EffectIntentPhase.RECONCILED and current.phase not in {
        EffectIntentPhase.PREPARED,
        EffectIntentPhase.RESULT_RECORDED,
    }:
        raise EffectIntentConflict(f"invalid effect intent transition: {current.phase}->{phase}")
    return EffectIntentRecord(
        current.intent,
        phase,
        effect,
        digest,
        current.consumption,
        current.consumption_digest,
    )


def is_authoritatively_resolved(effect: EffectReceipt | None) -> bool:
    return effect is not None and not effect.verification_required and effect.certainty in _RESOLVED


def require_consumable_effect(record: EffectIntentRecord) -> None:
    effect = record.effect
    if effect is None or effect.verification_required or effect.certainty not in _CONSUMABLE:
        raise EffectIntentConflict(
            "CONSUMED terminal requires resolved EFFECT_CONFIRMED/EFFECT_REJECTED proof"
        )


def consumed_transition(
    current: EffectIntentRecord,
    *,
    request_digest: str,
    consumption: EffectCompletionEvidence,
) -> EffectIntentRecord:
    """Pure CONSUMED terminal transition authority."""

    _require_request(current, request_digest)
    digest = consumption_digest(consumption)
    intent_id = current.intent.intent_id
    if current.phase is EffectIntentPhase.CONSUMED:
        if current.consumption_digest != digest:
            raise EffectIntentConflict(f"effect completion evidence conflict: {intent_id}")
        return current
    if current.phase not in {EffectIntentPhase.RESULT_RECORDED, EffectIntentPhase.RECONCILED}:
        raise EffectIntentConflict(f"cannot consume effect intent from phase: {current.phase}")
    require_consumable_effect(current)
    return EffectIntentRecord(
        current.intent,
        EffectIntentPhase.CONSUMED,
        current.effect,
        current.effect_digest,
        consumption,
        digest,
    )


def require_not_applied_compatible(record: EffectIntentRecord, proof: EffectReceipt) -> None:
    current = record.effect
    if not is_authoritatively_resolved(current):
        return
    assert current is not None
    if current.certainty is not EffectCertainty.NO_EFFECT:
        raise EffectIntentConflict("resolved external effect cannot become NOT_APPLIED")
    if record.effect_digest != effect_digest(proof):
        raise EffectIntentConflict("resolved NO_EFFECT proof conflict")


def not_applied_transition(
    current: EffectIntentRecord,
    *,
    request_digest: str,
    effect: EffectReceipt,
) -> EffectIntentRecord:
    """Pure NOT_APPLIED terminal transition authority."""

    if (
        effect.certainty is not EffectCertainty.NO_EFFECT
        or effect.request_digest != request_digest
        or effect.verification_required
    ):
        raise EffectIntentConflict(
            "NOT_APPLIED terminal requires authoritative bound NO_EFFECT proof"
        )
    _require_request(current, request_digest)
    _require_bound_effect(current, request_digest, effect)
    digest = effect_digest(effect)
    intent_id = current.intent.intent_id
    if current.phase is EffectIntentPhase.NOT_APPLIED:
        if current.effect_digest != digest:
            raise EffectIntentConflict(f"NOT_APPLIED proof conflict: {intent_id}")
        return current
    if current.phase is EffectIntentPhase.CONSUMED:
        raise EffectIntentConflict(f"consumed effect cannot become NOT_APPLIED: {intent_id}")
    require_not_applied_compatible(current, effect)
    if current.phase not in {
        EffectIntentPhase.PREPARED,
        EffectIntentPhase.RESULT_RECORDED,
        EffectIntentPhase.RECONCILED,
    }:
        raise EffectIntentConflict(f"cannot mark NOT_APPLIED from phase: {current.phase}")
    return EffectIntentRecord(
        current.intent,
        EffectIntentPhase.NOT_APPLIED,
        effect,
        digest,
        current.consumption,
        current.consumption_digest,
    )


__all__ = [
    "consumed_transition",
    "effect_transition",
    "is_authoritatively_resolved",
    "not_applied_transition",
    "prepare_transition",
    "require_consumable_effect",
    "require_not_applied_compatible",
]
