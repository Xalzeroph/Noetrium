"""Unified downstream API for Noetrium.

Downstream projects import this module only. Common authoring/runtime contracts
are re-exported directly. The complete registered surface remains discoverable
through system(), catalog(), and symbol_schema() without exposing internal
noetrium_platform implementation paths.
"""
from __future__ import annotations

from noetrium.contracts import *  # noqa: F401,F403
from noetrium.contracts import __all__ as _CONTRACT_EXPORTS
from noetrium.contracts.discovery import (
    DownstreamCapabilityCatalog,
    DownstreamSystemSurface,
    find_downstream_symbol_schema,
    load_downstream_capability_catalog,
    load_downstream_interface_schema,
)


def catalog() -> DownstreamCapabilityCatalog:
    """Return the validated generated capability catalog."""
    return load_downstream_capability_catalog()


def system(system_key: str):
    """Return one typed generated system facade from the unified API."""
    return catalog().facade(system_key)


def interface_schema() -> dict[str, object]:
    """Return the validated complete downstream interface schema."""
    return load_downstream_interface_schema()


def symbol_schema(system_key: str, module: str, symbol: str) -> dict[str, object]:
    """Return the generated schema for one public symbol."""
    return find_downstream_symbol_schema(system_key, module, symbol)


__all__ = tuple(dict.fromkeys((
    *_CONTRACT_EXPORTS,
    "DownstreamCapabilityCatalog",
    "DownstreamSystemSurface",
    "catalog",
    "system",
    "interface_schema",
    "symbol_schema",
)))
