"""Internal generated contract metadata.

Downstream projects use noetrium.api. This package contains JSON contracts,
read-only discovery metadata, and generated system facades used behind that
single public entrypoint.
"""
from __future__ import annotations

from .discovery import (
    DownstreamApiModule,
    DownstreamCapabilityCatalog,
    DownstreamCatalogIntegrityError,
    DownstreamSystemSurface,
    find_downstream_symbol_schema,
    load_downstream_capability_catalog,
    load_downstream_interface_schema,
    validate_downstream_capability_catalog,
    validate_downstream_interface_schema,
)
from .json import (
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
from .systems import SYSTEM_FACADES, SYSTEM_KEYS

__all__ = (
    "CanonicalDecodingError",
    "CanonicalDecodingFailureKind",
    "CanonicalEncodingError",
    "DigestValidationError",
    "DownstreamApiModule",
    "DownstreamCapabilityCatalog",
    "DownstreamCatalogIntegrityError",
    "DownstreamSystemSurface",
    "JsonDocument",
    "JsonInput",
    "JsonMutableValue",
    "JsonObject",
    "JsonScalar",
    "JsonValue",
    "SYSTEM_FACADES",
    "SYSTEM_KEYS",
    "Sha256Digest",
    "canonical_bytes",
    "canonical_digest",
    "canonical_text",
    "find_downstream_symbol_schema",
    "freeze_json",
    "load_downstream_capability_catalog",
    "load_downstream_interface_schema",
    "require_sha256",
    "strict_finite_json_bytes",
    "strict_finite_json_digest",
    "strict_finite_json_text",
    "strict_json_loads",
    "thaw_json",
    "validate_downstream_capability_catalog",
    "validate_downstream_interface_schema",
)
