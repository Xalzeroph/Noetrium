"""Research validation over the universal NoetriumUnit codec.

Persistence has exactly one codec: foundation.kernel.unit_codec.  This module
adds research-schema validation only; it owns no serialization algorithm and no
parallel document format.
"""
from __future__ import annotations

from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.unit_codec import (
    UNIT_DOCUMENT_SCHEMA,
    decode_unit,
    encode_unit,
)
from noetrium_platform.product.research_traits import validate_research_graph_semantics
from noetrium_platform.product.research_unit import require_research_root

RESEARCH_UNIT_MEDIA_TYPE = (
    "application/vnd." + UNIT_DOCUMENT_SCHEMA + "+json"
)


def _validated_research_unit(root: NoetriumUnit) -> NoetriumUnit:
    root = require_research_root(root)
    validate_research_graph_semantics(root)
    return root


def encode_research_unit(root: NoetriumUnit) -> bytes:
    return encode_unit(_validated_research_unit(root))


def decode_research_unit(raw: bytes) -> NoetriumUnit:
    return _validated_research_unit(decode_unit(raw))


__all__ = [
    "RESEARCH_UNIT_MEDIA_TYPE",
    "decode_research_unit",
    "encode_research_unit",
]
