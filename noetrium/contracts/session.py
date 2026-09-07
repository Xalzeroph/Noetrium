"""Convenient downstream facade for generic persistent sessions.

The symbol list is inherited from the generated runtime/session surface, so API
changes are picked up by regeneration rather than a second manual export list.
"""
from .systems.runtime__session import *  # noqa: F401,F403
from .systems.runtime__session import __all__, PACKAGE_PREFIX, SYSTEM_KEY

__all__ = list(__all__) + ["PACKAGE_PREFIX", "SYSTEM_KEY"]
