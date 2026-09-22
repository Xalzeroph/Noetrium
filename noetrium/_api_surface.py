"""Internal authority for modules projected through the unified downstream API.

Only Product/application composition sources may feed the unified Level-0 API.
Lower layers must be rolled up through adjacent facades first.
"""
from __future__ import annotations

UNIFIED_API_EXTRA_MODULES = (
    "noetrium.contracts.json",
    "noetrium_platform.platform",
    "components.api",
    "orchestration.api",
    "noetrium_platform.product.api",
)

__all__ = ["UNIFIED_API_EXTRA_MODULES"]
