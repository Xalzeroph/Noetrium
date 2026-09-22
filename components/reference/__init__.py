"""Canonical namespace for reusable Noetrium reference components.

Import a concrete subpackage explicitly; this namespace performs no eager
registration and owns no runtime state.
"""

__all__ = ["graph", "single_agent"]

from .environment_counter import ReferenceCounterDynamics, reference_counter_environment
__all__ = tuple(globals().get("__all__", ())) + ("ReferenceCounterDynamics", "reference_counter_environment")
