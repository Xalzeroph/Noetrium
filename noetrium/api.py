"""The single downstream API for Noetrium.

Lower system APIs are internal composition contracts. Research projects import
only this module, which re-exports the top-level Product Research OS surface.
"""
from __future__ import annotations

from noetrium_platform.product import api as _product
from noetrium_platform.product.api import *  # noqa: F401,F403


__all__ = _product.__all__
