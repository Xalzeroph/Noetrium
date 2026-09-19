from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

_HEX_RE = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_NUM_RE = re.compile(r"\b\d{3,}\b")


def _normalize_message(text: str) -> str:
    text = _HEX_RE.sub("<hex>", text)
    text = _NUM_RE.sub("<n>", text)
    return " ".join(text.split())[:512]


def _digest(signature: tuple[str, ...]) -> str:
    return hashlib.sha256(
        json.dumps(signature, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class FailureFingerprint:
    fingerprint: str
    family_fingerprint: str
    signature: tuple[str, ...]
    family_signature: tuple[str, ...]


def fingerprint_failure(failure: dict[str, object]) -> FailureFingerprint:
    family_signature = (
        str(failure.get("failure_domain") or ""),
        str(failure.get("failure_code") or ""),
        str(failure.get("stage") or ""),
        str(failure.get("component_id") or ""),
        str(failure.get("operation_type") or ""),
        str(failure.get("cause_type") or ""),
        _normalize_message(str(failure.get("cause_message") or "")),
        str(failure.get("effect_certainty") or ""),
        str(failure.get("recommended_recovery") or ""),
    )
    exact_signature = family_signature + (
        str(failure.get("taxonomy_spec_sha256") or "unbound"),
        str(failure.get("operation_payload_digest") or "unbound-request"),
    )
    return FailureFingerprint(
        _digest(exact_signature),
        _digest(family_signature),
        exact_signature,
        family_signature,
    )


__all__ = ["FailureFingerprint", "fingerprint_failure"]
