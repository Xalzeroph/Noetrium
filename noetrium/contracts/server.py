"""Downstream server and persistent-runtime contract facade.

This groups server identity, lifecycle, health, and session contracts while the
generated system surfaces remain the complete machine-maintained inventory.
"""
from .systems.runtime__server import *
from .systems.runtime__server import __all__ as _server_all
from .systems.runtime__server__health import *
from .systems.runtime__server__health import __all__ as _health_all
from .systems.runtime__server__identity import *
from .systems.runtime__server__identity import __all__ as _identity_all
from .systems.runtime__server__lifecycle import *
from .systems.runtime__server__lifecycle import __all__ as _lifecycle_all
from .systems.runtime__session import *
from .systems.runtime__session import __all__ as _session_all

__all__ = list(dict.fromkeys(
    (*_server_all, *_health_all, *_identity_all, *_lifecycle_all, *_session_all)
))
