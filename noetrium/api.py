"""Unified downstream API for Noetrium.

Downstream projects use this module only. Public symbols are resolved lazily
from the generated capability catalog, so importing the API does not construct
providers/runtimes or eagerly import the complete system surface.
"""
from __future__ import annotations

import importlib
from typing import Any

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


def system(system_key: str) -> Any:
    """Return one typed generated facade from the unified downstream API."""
    return catalog().facade(system_key)


def interface_schema() -> dict[str, Any]:
    """Return the validated complete downstream interface schema."""
    return load_downstream_interface_schema()


def symbol_schema(system_key: str, module: str, symbol: str) -> dict[str, Any]:
    """Return the generated schema for one public symbol."""
    return find_downstream_symbol_schema(system_key, module, symbol)


def _symbol_candidates(symbol: str) -> tuple[DownstreamSystemSurface, ...]:
    rows: list[DownstreamSystemSurface] = []
    for surface in catalog().systems:
        if surface.facade_module is None:
            continue
        if any(symbol in api.symbols for api in surface.api_modules):
            rows.append(surface)
    return tuple(rows)


def resolve(symbol: str) -> Any:
    """Resolve one public symbol across all registered system surfaces.

    A name exported by multiple surfaces is accepted only when every facade
    resolves to the same Python object. A true name collision must be selected
    explicitly through system(system_key).
    """
    if not isinstance(symbol, str) or not symbol or symbol.startswith("_"):
        raise AttributeError(symbol)
    candidates = _symbol_candidates(symbol)
    if not candidates:
        raise AttributeError(f"unknown Noetrium public symbol: {symbol}")

    resolved: list[tuple[str, Any]] = []
    for surface in candidates:
        module = importlib.import_module(surface.facade_module)
        if hasattr(module, symbol):
            resolved.append((surface.system_key, getattr(module, symbol)))
    if not resolved:
        raise AttributeError(f"unknown Noetrium public symbol: {symbol}")

    value = resolved[0][1]
    if all(candidate is value for _key, candidate in resolved[1:]):
        return value
    owners = tuple(key for key, _candidate in resolved)
    raise AttributeError(
        f"ambiguous Noetrium public symbol {symbol!r}; "
        f"select one with api.system(system_key).{symbol}; owners={owners!r}"
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
