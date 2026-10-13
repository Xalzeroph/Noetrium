from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel.operation import EffectCertainty
from noetrium_platform.capabilities.api import (
    EffectReconciliationDisposition,
    EffectReconciliationProof,
)


class EffectReconciliationOutcome(StrEnum):
    EXECUTED = "executed"
    NOT_EXECUTED = "not_executed"
    REJECTED = "rejected"
    INDETERMINATE = "indeterminate"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EffectReconciliationVerdict:
    request_id: str
    outcome: EffectReconciliationOutcome
    effect_id: str | None
    request_digest: str | None

    def __post_init__(self) -> None:
        if type(self.request_id) is not str or not self.request_id.strip():
            raise ValueError("effect reconciliation verdict request_id must be non-empty")
        if type(self.outcome) is not EffectReconciliationOutcome:
            raise ValueError("effect reconciliation verdict outcome must be typed")
        if (self.effect_id is None) != (self.request_digest is None):
            raise ValueError("effect reconciliation verdict effect identity is incomplete")
        for value, field in ((self.effect_id, "effect_id"), (self.request_digest, "request_digest")):
            if value is not None and (type(value) is not str or not value.strip()):
                raise ValueError(f"effect reconciliation verdict {field} must be non-empty or None")
        if self.outcome is not EffectReconciliationOutcome.UNKNOWN and self.effect_id is None:
            raise ValueError("resolved effect reconciliation verdict requires effect identity")


def project_effect_reconciliation(proof: EffectReconciliationProof) -> EffectReconciliationVerdict:
    if type(proof) is not EffectReconciliationProof:
        raise TypeError("effect reconciliation projection requires EffectReconciliationProof")
    if type(proof.request_id) is not str or not proof.request_id.strip():
        raise ValueError("effect reconciliation proof request_id must be non-empty")
    effect = proof.effect
    if proof.disposition is EffectReconciliationDisposition.UNKNOWN:
        if effect is None:
            return EffectReconciliationVerdict(
                proof.request_id,
                EffectReconciliationOutcome.UNKNOWN,
                None,
                None,
            )
        if effect.certainty not in {
            EffectCertainty.INDETERMINATE,
        }:
            raise ValueError(
                "indeterminate effect reconciliation requires provider indeterminate certainty"
            )
        return EffectReconciliationVerdict(
            proof.request_id,
            EffectReconciliationOutcome.INDETERMINATE,
            effect.effect_id,
            effect.request_digest,
        )
    if effect is None:
        raise ValueError("resolved effect reconciliation requires an effect receipt")
    if effect.certainty is EffectCertainty.INDETERMINATE:
        outcome = EffectReconciliationOutcome.UNKNOWN
    elif proof.disposition is EffectReconciliationDisposition.APPLIED and effect.certainty is EffectCertainty.EFFECT_CONFIRMED:
        outcome = EffectReconciliationOutcome.EXECUTED
    elif proof.disposition is EffectReconciliationDisposition.NOT_APPLIED and effect.certainty is EffectCertainty.NO_EFFECT:
        outcome = EffectReconciliationOutcome.NOT_EXECUTED
    elif proof.disposition is EffectReconciliationDisposition.REJECTED and effect.certainty is EffectCertainty.EFFECT_REJECTED:
        outcome = EffectReconciliationOutcome.REJECTED
    else:
        raise ValueError("effect reconciliation disposition/certainty pair is not authoritative")
    return EffectReconciliationVerdict(
        proof.request_id,
        outcome,
        effect.effect_id,
        effect.request_digest,
    )


__all__ = [
    "EffectReconciliationOutcome",
    "EffectReconciliationVerdict",
    "project_effect_reconciliation",
]
