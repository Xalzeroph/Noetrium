"""Pure effect-WAL transition algebra over NoetriumUnit records."""
from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectReceipt
from noetrium_platform.foundation.kernel.unit import NoetriumUnit

from .contracts import require_effect_receipt_request_digest
from .effect_units import (
    EffectIntentPhase,
    consumption_digest,
    effect_digest,
    effect_intent_record,
    intent_field,
    record_field,
)
from .journal import EffectIntentConflict, EffectIntentPrepareResult


_RESOLVED = {
    EffectCertainty.NO_EFFECT,
    EffectCertainty.EFFECT_CONFIRMED,
    EffectCertainty.EFFECT_REJECTED,
}
_CONSUMABLE = {
    EffectCertainty.EFFECT_CONFIRMED,
    EffectCertainty.EFFECT_REJECTED,
}
_INDETERMINATE = {EffectCertainty.INDETERMINATE}


def prepare_transition(
    current: NoetriumUnit | None,
    intent: NoetriumUnit,
) -> EffectIntentPrepareResult:
    if current is None:
        return EffectIntentPrepareResult(
            effect_intent_record(intent=intent, phase=EffectIntentPhase.PREPARED),
            True,
        )
    current_intent = record_field(current, "intent")
    if current_intent != intent:
        raise EffectIntentConflict(
            f"effect intent identity conflict: {intent_field(intent, 'intent_id')}"
        )
    return EffectIntentPrepareResult(current, False)


def _require_request(current: NoetriumUnit, request_digest: str) -> NoetriumUnit:
    intent = record_field(current, "intent")
    if intent_field(intent, "request_digest") != request_digest:
        raise EffectIntentConflict(
            f"effect request digest conflict: {intent_field(intent, 'intent_id')}"
        )
    return intent


def _require_bound_effect(
    current: NoetriumUnit,
    request_digest: str,
    effect: EffectReceipt | None,
) -> None:
    if effect is None:
        return
    intent = record_field(current, "intent")
    try:
        require_effect_receipt_request_digest(
            effect,
            expected_digest=request_digest,
            request_id=str(intent_field(intent, "request_id")),
            source="effect journal receipt",
        )
    except ValueError as exc:
        raise EffectIntentConflict(
            f"effect receipt request digest conflict: {intent_field(intent, 'intent_id')}"
        ) from exc


def effect_transition(
    current: NoetriumUnit,
    *,
    request_digest: str,
    phase: EffectIntentPhase,
    effect: EffectReceipt | None,
    result_snapshot: NoetriumUnit | None = None,
) -> NoetriumUnit:
    if phase not in {EffectIntentPhase.RESULT_RECORDED, EffectIntentPhase.RECONCILED}:
        raise ValueError(f"unsupported effect transition target: {phase}")
    intent = _require_request(current, request_digest)
    _require_bound_effect(current, request_digest, effect)
    digest = effect_digest(effect)
    intent_id = intent_field(intent, "intent_id")
    current_phase = record_field(current, "phase")
    current_effect_digest = record_field(current, "effect_digest")
    current_snapshot = record_field(current, "result_snapshot")

    if current_phase is phase:
        if current_effect_digest != digest or current_snapshot != result_snapshot:
            raise EffectIntentConflict(f"effect/result snapshot conflict: {intent_id}")
        return current
    if current_phase is EffectIntentPhase.RECONCILED:
        if current_effect_digest != digest or current_snapshot != result_snapshot:
            raise EffectIntentConflict(f"reconciled effect/result conflict: {intent_id}")
        return current
    if (
        phase is EffectIntentPhase.RESULT_RECORDED
        and current_phase is not EffectIntentPhase.PREPARED
    ):
        raise EffectIntentConflict(
            f"invalid effect intent transition: {current_phase}->{phase}"
        )
    if phase is EffectIntentPhase.RECONCILED and current_phase not in {
        EffectIntentPhase.PREPARED,
        EffectIntentPhase.RESULT_RECORDED,
    }:
        raise EffectIntentConflict(
            f"invalid effect intent transition: {current_phase}->{phase}"
        )
    return effect_intent_record(
        intent=intent,
        phase=phase,
        effect=effect,
        result_snapshot=result_snapshot,
        consumption=record_field(current, "consumption"),
    )


def require_terminal_result_match(
    current: NoetriumUnit,
    *,
    request_digest: str,
    effect: EffectReceipt,
    result_snapshot: NoetriumUnit | None,
) -> None:
    """Pure terminal-replay predicate: no synthetic PREPARED record is created.

    The replay invariant belongs to the effect transition algebra, not to
    storage adapters.  The current record is the journal-accepted terminal fact.
    """
    intent = _require_request(current, request_digest)
    _require_bound_effect(current, request_digest, effect)
    if record_field(current, "phase") not in {
        EffectIntentPhase.CONSUMED,
        EffectIntentPhase.NOT_APPLIED,
        EffectIntentPhase.INDETERMINATE,
    }:
        raise EffectIntentConflict("terminal effect result requires terminal record")
    if (
        record_field(current, "effect_digest") != effect_digest(effect)
        or record_field(current, "result_snapshot") != result_snapshot
    ):
        raise EffectIntentConflict(
            f"terminal effect/result conflict: {intent_field(intent, 'intent_id')}"
        )


def is_authoritatively_resolved(effect: EffectReceipt | None) -> bool:
    return effect is not None and effect.certainty in _RESOLVED


def require_consumable_effect(record: NoetriumUnit) -> None:
    effect = record_field(record, "effect")
    if effect is None or effect.certainty not in _CONSUMABLE:
        raise EffectIntentConflict(
            "CONSUMED terminal requires resolved EFFECT_CONFIRMED/EFFECT_REJECTED proof"
        )


def consumed_transition(
    current: NoetriumUnit,
    *,
    request_digest: str,
    consumption: NoetriumUnit,
) -> NoetriumUnit:
    intent = _require_request(current, request_digest)
    digest = consumption_digest(consumption)
    intent_id = intent_field(intent, "intent_id")
    current_phase = record_field(current, "phase")
    if current_phase is EffectIntentPhase.CONSUMED:
        if record_field(current, "consumption_digest") != digest:
            raise EffectIntentConflict(
                f"effect completion evidence conflict: {intent_id}"
            )
        return current
    if current_phase not in {
        EffectIntentPhase.RESULT_RECORDED,
        EffectIntentPhase.RECONCILED,
    }:
        raise EffectIntentConflict(
            f"cannot consume effect intent from phase: {current_phase}"
        )
    require_consumable_effect(current)
    return effect_intent_record(
        intent=intent,
        phase=EffectIntentPhase.CONSUMED,
        effect=record_field(current, "effect"),
        result_snapshot=record_field(current, "result_snapshot"),
        consumption=consumption,
    )


def indeterminate_transition(
    current: NoetriumUnit,
    *,
    request_digest: str,
    effect: EffectReceipt,
) -> NoetriumUnit:
    if effect.certainty not in _INDETERMINATE or effect.request_digest != request_digest:
        raise EffectIntentConflict(
            "INDETERMINATE terminal requires bound provider indeterminate evidence"
        )
    intent = _require_request(current, request_digest)
    _require_bound_effect(current, request_digest, effect)
    digest = effect_digest(effect)
    intent_id = intent_field(intent, "intent_id")
    current_phase = record_field(current, "phase")
    if current_phase is EffectIntentPhase.INDETERMINATE:
        if record_field(current, "effect_digest") != digest:
            raise EffectIntentConflict(f"INDETERMINATE proof conflict: {intent_id}")
        return current
    if current_phase in {
        EffectIntentPhase.CONSUMED,
        EffectIntentPhase.NOT_APPLIED,
    }:
        raise EffectIntentConflict(
            f"resolved terminal effect cannot become INDETERMINATE: {intent_id}"
        )
    if current_phase not in {
        EffectIntentPhase.PREPARED,
        EffectIntentPhase.RESULT_RECORDED,
        EffectIntentPhase.RECONCILED,
    }:
        raise EffectIntentConflict(
            f"cannot mark INDETERMINATE from phase: {current_phase}"
        )
    return effect_intent_record(
        intent=intent,
        phase=EffectIntentPhase.INDETERMINATE,
        effect=effect,
        result_snapshot=record_field(current, "result_snapshot"),
        consumption=record_field(current, "consumption"),
    )


def require_not_applied_compatible(
    record: NoetriumUnit,
    proof: EffectReceipt,
) -> None:
    current = record_field(record, "effect")
    if not is_authoritatively_resolved(current):
        return
    assert current is not None
    if current.certainty is not EffectCertainty.NO_EFFECT:
        raise EffectIntentConflict("resolved external effect cannot become NOT_APPLIED")
    if record_field(record, "effect_digest") != effect_digest(proof):
        raise EffectIntentConflict("resolved NO_EFFECT proof conflict")


def not_applied_transition(
    current: NoetriumUnit,
    *,
    request_digest: str,
    effect: EffectReceipt,
) -> NoetriumUnit:
    if (
        effect.certainty is not EffectCertainty.NO_EFFECT
        or effect.request_digest != request_digest
    ):
        raise EffectIntentConflict(
            "NOT_APPLIED terminal requires authoritative bound NO_EFFECT proof"
        )
    intent = _require_request(current, request_digest)
    _require_bound_effect(current, request_digest, effect)
    digest = effect_digest(effect)
    intent_id = intent_field(intent, "intent_id")
    current_phase = record_field(current, "phase")
    if current_phase is EffectIntentPhase.NOT_APPLIED:
        if record_field(current, "effect_digest") != digest:
            raise EffectIntentConflict(f"NOT_APPLIED proof conflict: {intent_id}")
        return current
    if current_phase is EffectIntentPhase.CONSUMED:
        raise EffectIntentConflict(
            f"consumed effect cannot become NOT_APPLIED: {intent_id}"
        )
    require_not_applied_compatible(current, effect)
    if current_phase not in {
        EffectIntentPhase.PREPARED,
        EffectIntentPhase.RESULT_RECORDED,
        EffectIntentPhase.RECONCILED,
    }:
        raise EffectIntentConflict(
            f"cannot mark NOT_APPLIED from phase: {current_phase}"
        )
    return effect_intent_record(
        intent=intent,
        phase=EffectIntentPhase.NOT_APPLIED,
        effect=effect,
        result_snapshot=record_field(current, "result_snapshot"),
        consumption=record_field(current, "consumption"),
    )


__all__ = [
    "consumed_transition",
    "effect_transition",
    "indeterminate_transition",
    "is_authoritatively_resolved",
    "not_applied_transition",
    "prepare_transition",
    "require_consumable_effect",
    "require_not_applied_compatible",
]
