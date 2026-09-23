"""Canonical source list for the unified downstream Research OS API.

Registered lower systems are composition authorities, not independent downstream
SDKs. The product layer is the sole source projected through noetrium.api.
"""
from __future__ import annotations

UNIFIED_API_EXTRA_MODULES = (
    "noetrium_platform.product.api",
)

__all__ = ["UNIFIED_API_EXTRA_MODULES"]
