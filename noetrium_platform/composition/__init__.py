"""Explicit composition modules.

Import concrete composition submodules directly so dependency graphs expose exactly
which runtime domains are being assembled.
"""

__all__: tuple[str, ...] = ()

from .managed_research_runtime import (
    ManagedResearchRuntime,
    build_local_managed_research_runtime,
)

__all__ = tuple(globals().get("__all__", ())) + (
    "ManagedResearchRuntime",
    "build_local_managed_research_runtime",
)
