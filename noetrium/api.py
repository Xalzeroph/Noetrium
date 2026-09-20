"""Unified downstream API for Noetrium.

Downstream projects use this module only. Public symbols are resolved lazily
from generated system facades and stable product/helper surfaces, so importing
Noetrium never constructs providers, runtimes, or the complete system graph.
"""
from __future__ import annotations

from functools import lru_cache
import importlib
from typing import Any

from noetrium.contracts.discovery import (
    DownstreamCapabilityCatalog,
    DownstreamSystemSurface,
    find_downstream_symbol_schema,
    load_downstream_capability_catalog,
    load_downstream_interface_schema,
)

_EXTRA_MODULES = (
    "noetrium.contracts.json",
    "noetrium.platform",
    "noetrium_platform.research.experimentation.study.runtime",
    "noetrium_platform.research.experimentation.workbench.providers",
    "noetrium_platform.research.experimentation.workbench.runtime",
)


@lru_cache(maxsize=1)
def catalog() -> DownstreamCapabilityCatalog:
    """Return the validated generated capability catalog."""
    return load_downstream_capability_catalog()


def system(system_key: str) -> Any:
    """Return one typed generated facade from the unified downstream API."""
    return catalog().facade(system_key)


@lru_cache(maxsize=1)
def interface_schema() -> dict[str, Any]:
    """Return the validated complete downstream interface schema."""
    return load_downstream_interface_schema()


def symbol_schema(system_key: str, module: str, symbol: str) -> dict[str, Any]:
    """Return the generated schema for one registered public symbol."""
    return find_downstream_symbol_schema(system_key, module, symbol)


def _system_candidates(symbol: str) -> tuple[tuple[str, Any], ...]:
    resolved: list[tuple[str, Any]] = []
    current = catalog()
    for system_key in current.owners(symbol):
        surface = current.system(system_key)
        if surface.facade_module is None:
            continue
        module = importlib.import_module(surface.facade_module)
        if hasattr(module, symbol):
            resolved.append((surface.system_key, getattr(module, symbol)))
    return tuple(resolved)


def _extra_candidates(symbol: str) -> tuple[tuple[str, Any], ...]:
    resolved: list[tuple[str, Any]] = []
    for module_name in _EXTRA_MODULES:
        module = importlib.import_module(module_name)
        exports = getattr(module, "__all__", ())
        if symbol in exports and hasattr(module, symbol):
            resolved.append((module_name, getattr(module, symbol)))
    return tuple(resolved)


def resolve(symbol: str) -> Any:
    """Resolve one public symbol across the complete unified API.

    Multiple owners are accepted only when they resolve to the same Python
    object. A true name collision must be selected explicitly through
    system(system_key).
    """
    if not isinstance(symbol, str) or not symbol or symbol.startswith("_"):
        raise AttributeError(symbol)
    resolved = (*_system_candidates(symbol), *_extra_candidates(symbol))
    if not resolved:
        raise AttributeError(f"unknown Noetrium public symbol: {symbol}")

    value = resolved[0][1]
    if all(candidate is value for _owner, candidate in resolved[1:]):
        return value
    owners = tuple(owner for owner, _candidate in resolved)
    raise AttributeError(
        f"ambiguous Noetrium public symbol {symbol!r}; "
        f"select a registered system with api.system(system_key).{symbol} "
        f"or use a more specific symbol; owners={owners!r}"
    )


def __getattr__(name: str) -> Any:
    value = resolve(name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    names = {
        "DownstreamCapabilityCatalog",
        "DownstreamSystemSurface",
        "catalog",
        "system",
        "resolve",
        "interface_schema",
        "symbol_schema",
    }
    for surface in catalog().systems:
        for module in surface.api_modules:
            names.update(module.symbols)
    for module_name in _EXTRA_MODULES:
        module = importlib.import_module(module_name)
        names.update(getattr(module, "__all__", ()))
    return sorted(names)


__all__ = (
    "DownstreamCapabilityCatalog",
    "DownstreamSystemSurface",
    "catalog",
    "system",
    "resolve",
    "interface_schema",
    "symbol_schema",
)
