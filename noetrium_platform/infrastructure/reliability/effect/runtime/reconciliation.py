"""Authoritative effect reconciliation over Unit-native WAL truth."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import EffectCertainty
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectIntentJournal,
    EffectIntentPhase,
    EffectReconciliationDisposition,
    EffectReconciliationProof,
    EffectRecoveryRequired,
    intent_field,
    record_field,
    require_effect_receipt_request_digest,
)


@runtime_checkable
class EffectReconciliationProvider(Protocol):
    def reconcile(
        self,
        intent: NoetriumUnit,
        record: NoetriumUnit,
    ) -> EffectReconciliationProof: ...


@dataclass(frozen=True, slots=True)
class EffectReconciliationResult:
    intent_id: str
    disposition: EffectReconciliationDisposition
    record: NoetriumUnit
    changed: bool


class EffectReconciliationService:
    """Bridge Physical observation into the durable Effect Journal Authority."""

    def __init__(
        self,
        journal: EffectIntentJournal,
        provider: EffectReconciliationProvider,
    ) -> None:
        if not isinstance(journal, EffectIntentJournal):
            raise TypeError("journal must implement EffectIntentJournal")
        if not isinstance(provider, EffectReconciliationProvider):
            raise TypeError("provider must implement EffectReconciliationProvider")
        self.journal = journal
        self.provider = provider

    def reconcile(self, intent_id: str) -> EffectReconciliationResult:
        current = self.journal.load(intent_id)
        if current is None:
            raise EffectRecoveryRequired(
                f"effect intent does not exist: {intent_id}"
            )
        phase = record_field(current, "phase")
        effect = record_field(current, "effect")
        intent = record_field(current, "intent")
        request_id = str(intent_field(intent, "request_id"))
        request_digest = str(intent_field(intent, "request_digest"))

        if phase is EffectIntentPhase.CONSUMED:
            disposition = (
                EffectReconciliationDisposition.REJECTED
                if effect is not None
                and effect.certainty is EffectCertainty.EFFECT_REJECTED
                else EffectReconciliationDisposition.APPLIED
            )
            return EffectReconciliationResult(
                intent_id, disposition, current, False
            )
        if phase is EffectIntentPhase.NOT_APPLIED:
            return EffectReconciliationResult(
                intent_id,
                EffectReconciliationDisposition.NOT_APPLIED,
                current,
                False,
            )
        if phase is EffectIntentPhase.INDETERMINATE:
            return EffectReconciliationResult(
                intent_id,
                EffectReconciliationDisposition.UNKNOWN,
                current,
                False,
            )
        if phase is EffectIntentPhase.RECONCILED:
            if effect is None:
                raise EffectRecoveryRequired(
                    f"reconciled effect lacks a receipt: {intent_id}"
                )
            disposition = (
                EffectReconciliationDisposition.REJECTED
                if effect.certainty is EffectCertainty.EFFECT_REJECTED
                else EffectReconciliationDisposition.APPLIED
            )
            return EffectReconciliationResult(
                intent_id, disposition, current, False
            )

        proof = self.provider.reconcile(intent, current)
        if proof.request_id != request_id:
            raise EffectRecoveryRequired(
                "reconciliation proof request identity mismatch"
            )
        if proof.disposition is EffectReconciliationDisposition.UNKNOWN:
            proof_effect = proof.effect
            if proof_effect is None:
                raise EffectRecoveryRequired(
                    f"provider indeterminate reconciliation lacks effect receipt: "
                    f"{intent_id}"
                )
            require_effect_receipt_request_digest(
                proof_effect,
                expected_digest=request_digest,
                request_id=request_id,
                source="indeterminate reconciliation proof",
            )
            if proof_effect.certainty is not EffectCertainty.INDETERMINATE:
                raise EffectRecoveryRequired(
                    f"provider indeterminate reconciliation carries resolved "
                    f"certainty: {intent_id}"
                )
            updated = self.journal.record_indeterminate(
                intent_id,
                request_digest=request_digest,
                effect=proof_effect,
            )
            return EffectReconciliationResult(
                intent_id,
                EffectReconciliationDisposition.UNKNOWN,
                updated,
                updated != current,
            )

        proof_effect = proof.effect
        if proof_effect is None:
            raise EffectRecoveryRequired(
                f"reconciliation disposition lacks an effect proof: {intent_id}"
            )
        require_effect_receipt_request_digest(
            proof_effect,
            expected_digest=request_digest,
            request_id=request_id,
            source="reconciliation proof",
        )
        if (
            proof.disposition is EffectReconciliationDisposition.NOT_APPLIED
            or (
                proof.disposition is EffectReconciliationDisposition.REJECTED
                and proof_effect.certainty is EffectCertainty.NO_EFFECT
            )
        ):
            updated = self.journal.record_not_applied(
                intent_id,
                request_digest=request_digest,
                effect=proof_effect,
            )
            return EffectReconciliationResult(
                intent_id,
                EffectReconciliationDisposition.NOT_APPLIED,
                updated,
                updated != current,
            )
        updated = self.journal.record_reconciled(
            intent_id,
            request_digest=request_digest,
            effect=proof_effect,
        )
        return EffectReconciliationResult(
            intent_id,
            proof.disposition,
            updated,
            updated != current,
        )

    def reconcile_many(
        self,
        intent_ids: tuple[str, ...],
    ) -> tuple[EffectReconciliationResult, ...]:
        if type(intent_ids) is not tuple:
            raise TypeError("intent_ids must be a tuple")
        if len(set(intent_ids)) != len(intent_ids):
            raise ValueError("intent_ids must be unique")
        return tuple(self.reconcile(intent_id) for intent_id in intent_ids)


__all__ = [
    "EffectReconciliationProvider",
    "EffectReconciliationResult",
    "EffectReconciliationService",
]
