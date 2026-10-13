"""Strict JSON and digest contracts exposed to downstream projects.

The implementation remains owned by the Platform kernel; this module is the
stable public import surface for typed component authors.
"""

from noetrium_platform.foundation.kernel.kernel import (
    CanonicalDecodingError,
    CanonicalDecodingFailureKind,
    CanonicalEncodingError,
    DigestValidationError,
    JsonDocument,
    JsonInput,
    JsonMutableValue,
    JsonObject,
    JsonScalar,
    JsonValue,
    Sha256Digest,
    canonical_bytes,
    canonical_digest,
    canonical_text,
    freeze_json,
    require_sha256,
    strict_finite_json_bytes,
    strict_finite_json_digest,
    strict_finite_json_text,
    strict_json_loads,
    thaw_json,
)

__all__ = [
    "CanonicalDecodingError", "CanonicalDecodingFailureKind",
    "CanonicalEncodingError", "DigestValidationError", "JsonDocument",
    "JsonInput", "JsonMutableValue", "JsonObject", "JsonScalar", "JsonValue",
    "Sha256Digest", "canonical_bytes", "canonical_digest", "canonical_text",
    "freeze_json", "require_sha256", "strict_finite_json_bytes",
    "strict_finite_json_digest", "strict_finite_json_text", "strict_json_loads",
    "thaw_json",
]
