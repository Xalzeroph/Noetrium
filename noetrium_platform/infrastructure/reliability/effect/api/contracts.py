from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib

from noetrium_platform.foundation.kernel.kernel import EffectReceipt


@dataclass(frozen=True, slots=True)
class PreparedEffectHandle:
    """Opaque provider recovery material for one prepared external effect."""

    request_id: str
    request_digest: str
    provider_schema: str
    opaque_payload: bytes = field(repr=False)
    payload_sha256: str = ""
    provider_instance_id: str | None = None

    @classmethod
    def build(
        cls,
        *,
        request_id: str,
        request_digest: str,
        provider_schema: str,
        opaque_payload: bytes,
        provider_instance_id: str | None = None,
    ) -> "PreparedEffectHandle":
        payload = bytes(opaque_payload)
        return cls(
            request_id,
            request_digest,
            provider_schema,
            payload,
            hashlib.sha256(payload).hexdigest(),
            provider_instance_id,
        )

    def __post_init__(self) -> None:
        if not self.request_id.strip() or not self.request_digest.strip() or not self.provider_schema.strip():
            raise ValueError("prepared effect handle identity fields must be non-empty")
        actual = hashlib.sha256(self.opaque_payload).hexdigest()
        if actual != self.payload_sha256:
            raise ValueError("prepared effect handle payload checksum mismatch")


class EffectReconciliationDisposition(StrEnum):
    APPLIED = "applied"
    REJECTED = "rejected"
    NOT_APPLIED = "not_applied"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EffectReconciliationProof:
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
    """Validate generic request/effect correlation without provider semantics."""

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
    "PreparedEffectHandle",
    "require_effect_receipt_request_digest",
]
