"""Internal authority for modules projected through the unified downstream API.

These modules are implementation/aggregation sources only. Downstream projects
still import exclusively from noetrium.api.
"""
from __future__ import annotations

UNIFIED_API_EXTRA_MODULES = (
    "noetrium.contracts.json",
    "noetrium_platform.platform",
    "components.api",
    "orchestration.api",
    "noetrium_platform.research.experimentation.study.runtime",
    "noetrium_platform.research.experimentation.workbench.providers",
    "noetrium_platform.research.experimentation.workbench.runtime",
)

__all__ = ["UNIFIED_API_EXTRA_MODULES"]
