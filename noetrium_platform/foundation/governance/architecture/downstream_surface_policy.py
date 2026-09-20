"""Canonical policy for generated downstream symbol exposure.

This module classifies names only. It does not select providers, runtimes, or
authorities. Generators and audits consume the same policy so the public surface
cannot disagree about internal metadata exports.
"""
from __future__ import annotations

DOWNSTREAM_EXCLUDED_SYMBOLS = frozenset({
    "AUTHORITY",
    "CONTRACT",
    "MUST_NOT_OWN",
    "NODE",
    "OWNS",
    "SYSTEM",
    "SystemLeafContract",
    "contract",
    "JsonDocument",
    "JsonInput",
    "JsonMutableValue",
    "JsonObject",
    "JsonScalar",
    "JsonValue",
    "Sha256Digest",
    "canonical_bytes",
    "canonical_digest",
    "canonical_text",
    "freeze_json",
    "require_sha256",
    "strict_finite_json_bytes",
    "strict_finite_json_digest",
    "strict_finite_json_text",
    "strict_json_loads",
    "thaw_json",
})


def downstream_symbols(names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in names if name not in DOWNSTREAM_EXCLUDED_SYMBOLS)


__all__ = ["DOWNSTREAM_EXCLUDED_SYMBOLS", "downstream_symbols"]
