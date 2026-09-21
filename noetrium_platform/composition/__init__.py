"""Explicit composition modules.

Import concrete composition submodules directly so dependency graphs expose exactly
which runtime domains are being assembled.
"""

__all__: tuple[str, ...] = ()

from .managed_observability import ManagedObservability, build_managed_observability
from .managed_research_runtime import (
    ManagedResearchRuntime,
    build_local_managed_research_runtime,
)

__all__ = tuple(globals().get("__all__", ())) + (
    "ManagedObservability",
    "ManagedResearchRuntime",
    "build_local_managed_research_runtime",
    "build_managed_observability",
)
