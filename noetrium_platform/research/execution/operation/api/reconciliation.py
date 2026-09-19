from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel.operation import EffectCertainty
from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectReconciliationDisposition,
    EffectReconciliationProof,
)


class EffectReconciliationOutcome(StrEnum):
    EXECUTED = "executed"
    NOT_EXECUTED = "not_executed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EffectReconciliationVerdict:
    request_id: str
    outcome: EffectReconciliationOutcome
    effect_id: str | None
    request_digest: str | None
    verification_required: bool

    def __post_init__(self) -> None:
        if type(self.request_id) is not str or not self.request_id.strip():
            raise ValueError("effect reconciliation verdict request_id must be non-empty")
        if type(self.outcome) is not EffectReconciliationOutcome:
            raise ValueError("effect reconciliation verdict outcome must be typed")
        if type(self.verification_required) is not bool:
            raise ValueError("effect reconciliation verdict verification_required must be boolean")
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
        return EffectReconciliationVerdict(
            proof.request_id,
            EffectReconciliationOutcome.UNKNOWN,
            None if effect is None else effect.effect_id,
            None if effect is None else effect.request_digest,
            False if effect is None else effect.verification_required,
        )
    if effect is None:
        raise ValueError("resolved effect reconciliation requires an effect receipt")
    if effect.certainty in {EffectCertainty.EFFECT_POSSIBLE, EffectCertainty.EFFECT_UNKNOWN}:
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
        effect.verification_required,
    )


__all__ = [
    "EffectReconciliationOutcome",
    "EffectReconciliationVerdict",
    "project_effect_reconciliation",
]
