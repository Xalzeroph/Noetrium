from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import EffectReceipt


class EffectReconciliationDisposition(StrEnum):
    APPLIED = "applied"
    REJECTED = "rejected"
    NOT_APPLIED = "not_applied"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EffectReconciliationProof:
    """Ephemeral provider observation; durable WAL materializes its receipt as Unit."""

    request_id: str
    disposition: EffectReconciliationDisposition
    effect: EffectReceipt | None
    diagnostics: dict[str, object] = field(default_factory=dict)


def require_effect_receipt_request_digest(
    effect: EffectReceipt,
    *,
    expected_digest: str,
    request_id: str | None = None,
    source: str = "effect receipt",
) -> EffectReceipt:
    if effect.request_digest != expected_digest:
        suffix = f" request_id={request_id}" if request_id else ""
        raise ValueError(
            f"{source} request digest mismatch:{suffix} "
            f"expected={expected_digest} actual={effect.request_digest}"
        )
    return effect


__all__ = [
    "EffectReconciliationDisposition",
    "EffectReconciliationProof",
    "require_effect_receipt_request_digest",
]
