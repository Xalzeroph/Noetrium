"""Authoritative effect reconciliation orchestration.

The provider observes the external world; the existing EffectIntentJournal
remains the only writer of effect lifecycle facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectReceipt
from noetrium_platform.infrastructure.reliability.effect.api.contracts import (
    EffectReconciliationDisposition,
    EffectReconciliationProof,
    require_effect_receipt_request_digest,
)
from noetrium_platform.infrastructure.reliability.effect.api.journal import (
    EffectIntent,
    EffectIntentJournal,
    EffectIntentPhase,
    EffectIntentRecord,
    EffectRecoveryRequired,
)


@runtime_checkable
class EffectReconciliationProvider(Protocol):
    def reconcile(
        self,
        intent: EffectIntent,
        record: EffectIntentRecord,
    ) -> EffectReconciliationProof: ...


@dataclass(frozen=True, slots=True)
class EffectReconciliationResult:
    intent_id: str
    disposition: EffectReconciliationDisposition
    record: EffectIntentRecord
    changed: bool


class EffectReconciliationService:
    """Bridge external observation to the durable effect state machine."""

    def __init__(self, journal: EffectIntentJournal, provider: EffectReconciliationProvider) -> None:
        if not isinstance(journal, EffectIntentJournal):
            raise TypeError("journal must implement EffectIntentJournal")
        if not isinstance(provider, EffectReconciliationProvider):
            raise TypeError("provider must implement EffectReconciliationProvider")
        self.journal = journal
        self.provider = provider

    def reconcile(self, intent_id: str) -> EffectReconciliationResult:
        current = self.journal.load(intent_id)
        if current is None:
            raise EffectRecoveryRequired(f"effect intent does not exist: {intent_id}")
        if current.phase is EffectIntentPhase.CONSUMED:
            disposition = (
                EffectReconciliationDisposition.REJECTED
                if current.effect is not None
                and current.effect.certainty is EffectCertainty.EFFECT_REJECTED
                else EffectReconciliationDisposition.APPLIED
            )
            return EffectReconciliationResult(intent_id, disposition, current, False)
        if current.phase is EffectIntentPhase.NOT_APPLIED:
            return EffectReconciliationResult(
                intent_id, EffectReconciliationDisposition.NOT_APPLIED, current, False
            )
        if current.phase is EffectIntentPhase.RECONCILED:
            if current.effect is None:
                raise EffectRecoveryRequired(
                    f"reconciled effect lacks a receipt: {intent_id}"
                )
            disposition = (
                EffectReconciliationDisposition.REJECTED
                if current.effect.certainty is EffectCertainty.EFFECT_REJECTED
                else EffectReconciliationDisposition.APPLIED
            )
            return EffectReconciliationResult(intent_id, disposition, current, False)
        proof = self.provider.reconcile(current.intent, current)
        if proof.request_id != current.intent.request_id:
            raise EffectRecoveryRequired("reconciliation proof request identity mismatch")
        if proof.disposition is EffectReconciliationDisposition.UNKNOWN:
            if proof.effect is not None:
                raise EffectRecoveryRequired(
                    f"UNKNOWN reconciliation cannot carry an effect receipt: {intent_id}"
                )
            return EffectReconciliationResult(
                intent_id, EffectReconciliationDisposition.UNKNOWN, current, False
            )
        effect = proof.effect
        if effect is None:
            raise EffectRecoveryRequired(
                f"reconciliation disposition lacks an effect proof: {intent_id}"
            )
        require_effect_receipt_request_digest(
            effect,
            expected_digest=current.intent.request_digest,
            request_id=current.intent.request_id,
            source="reconciliation proof",
        )
        if (
            proof.disposition is EffectReconciliationDisposition.NOT_APPLIED
            or (
                proof.disposition is EffectReconciliationDisposition.REJECTED
                and effect.certainty is EffectCertainty.NO_EFFECT
            )
        ):
            updated = self.journal.record_not_applied(
                intent_id,
                request_digest=current.intent.request_digest,
                effect=effect,
            )
            return EffectReconciliationResult(
                intent_id, EffectReconciliationDisposition.NOT_APPLIED, updated, updated != current
            )
        updated = self.journal.record_reconciled(
            intent_id,
            request_digest=current.intent.request_digest,
            effect=effect,
        )
        return EffectReconciliationResult(
            intent_id, proof.disposition, updated, updated != current
        )

    def reconcile_many(self, intent_ids: tuple[str, ...]) -> tuple[EffectReconciliationResult, ...]:
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
