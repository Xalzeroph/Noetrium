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
    load_downstream_capability_catalog,
    load_downstream_interface_schema,
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


def owners(symbol: str) -> tuple[str, ...]:
    """Return public owners without importing implementation modules."""
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("symbol must be non-empty text")
    current = catalog()
    registered = current.owners(symbol)
    if registered:
        return registered
    direct = current.direct_source(symbol)
    if direct is not None:
        return (direct,)
    return current.ambiguous_sources(symbol)

def search(query: str, *, limit: int = 50) -> tuple[ApiSymbolMatch, ...]:
    """Search the unified symbol index without importing implementations."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be non-empty text")
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be positive")
    needle = query.casefold()
    current = catalog()
    names = (
        set(current.symbol_index)
        | set(current.direct_symbol_sources)
        | set(current.ambiguous_symbol_sources)
    )
    rows = [
        ApiSymbolMatch(symbol, owners(symbol))
        for symbol in names
        if needle in symbol.casefold()
        or any(needle in owner.casefold() for owner in owners(symbol))
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
    registered = set(catalog().owners(symbol))
    if not registered:
        sources = ()
        direct = catalog().direct_source(symbol)
        if direct is not None:
            sources = (direct,)
        else:
            sources = catalog().ambiguous_sources(symbol)
        for module_name in sources:
            rows.append({
                "system_key": None,
                "module": module_name,
                "schema": {
                    "name": symbol,
                    "kind": "python_export",
                    "qualified_name": f"{module_name}.{symbol}",
                },
            })
    return tuple(rows)


@lru_cache(maxsize=None)
def resolve(symbol: str) -> Any:
    """Resolve one public symbol through the generated v4 resolution index."""
    if not isinstance(symbol, str) or not symbol or symbol.startswith("_"):
        raise AttributeError(symbol)
    current = catalog()
    source = current.direct_source(symbol)
    if source is not None:
        module = importlib.import_module(source)
        try:
            return getattr(module, symbol)
        except AttributeError as exc:
            raise AttributeError(
                f"generated Noetrium symbol source is stale: {source}.{symbol}"
            ) from exc

    ambiguous = current.ambiguous_sources(symbol)
    if ambiguous:
        registered = current.owners(symbol)
        hint = (
            f"select one with api.system(system_key).{symbol}; owners={registered!r}"
            if registered
            else f"symbol sources are ambiguous: {ambiguous!r}"
        )
        raise AttributeError(
            f"ambiguous Noetrium public symbol {symbol!r}; {hint}"
        )
    raise AttributeError(f"unknown Noetrium public symbol: {symbol}")

def __getattr__(name: str) -> Any:
    value = resolve(name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    current = catalog()
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
        *current.direct_symbol_sources,
        *current.ambiguous_symbol_sources,
    }
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
)
