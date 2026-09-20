"""Unified downstream API for Noetrium.

Downstream projects use this module only. Public symbols are resolved lazily
from generated system facades and stable product/helper surfaces, so importing
Noetrium never constructs providers, runtimes, or the complete system graph.
"""
from __future__ import annotations

from dataclasses import dataclass
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
    "noetrium_platform.platform",
    "components.api",
    "orchestration.api",
    "noetrium_platform.research.experimentation.study.runtime",
    "noetrium_platform.research.experimentation.workbench.providers",
    "noetrium_platform.research.experimentation.workbench.runtime",
)


@dataclass(frozen=True, slots=True)
class ApiSymbolMatch:
    symbol: str
    owners: tuple[str, ...]


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


def owners(symbol: str) -> tuple[str, ...]:
    """Return registered system owners for one public symbol."""
    return catalog().owners(symbol)


def search(query: str, *, limit: int = 50) -> tuple[ApiSymbolMatch, ...]:
    """Search the unified public symbol index without importing implementations."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be non-empty text")
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be positive")
    needle = query.casefold()
    rows = [
        ApiSymbolMatch(symbol, tuple(system_keys))
        for symbol, system_keys in catalog().symbol_index.items()
        if needle in symbol.casefold()
        or any(needle in system_key.casefold() for system_key in system_keys)
    ]
    rows.sort(key=lambda row: (row.symbol.casefold() != needle, row.symbol.casefold()))
    return tuple(rows[:limit])


def describe(symbol: str) -> tuple[dict[str, Any], ...]:
    """Return all generated schemas for a symbol without requiring module paths."""
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("symbol must be non-empty text")
    owner_keys = set(owners(symbol))
    if not owner_keys:
        return ()
    rows: list[dict[str, Any]] = []
    for system_row in interface_schema()["systems"]:
        if system_row["system_key"] not in owner_keys:
            continue
        for api_module in system_row["api_modules"]:
            for schema in api_module["symbol_schemas"]:
                if schema["name"] == symbol:
                    rows.append({
                        "system_key": system_row["system_key"],
                        "module": api_module["module"],
                        "schema": schema,
                    })
    return tuple(rows)


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
        "ApiSymbolMatch",
        "DownstreamCapabilityCatalog",
        "DownstreamSystemSurface",
        "catalog",
        "system",
        "resolve",
        "owners",
        "search",
        "describe",
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
    "ApiSymbolMatch",
    "DownstreamCapabilityCatalog",
    "DownstreamSystemSurface",
    "catalog",
    "system",
    "resolve",
    "owners",
    "search",
    "describe",
    "interface_schema",
    "symbol_schema",
)
