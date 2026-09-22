"""Unified downstream API for Noetrium.

Downstream projects use this module only. Public symbols are resolved lazily
from generated system facades and stable product/helper surfaces, so importing
Noetrium never constructs providers, runtimes, or the complete system graph.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
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



@lru_cache(maxsize=1)
def interface_schema() -> dict[str, Any]:
    """Return the validated complete downstream interface schema."""
    return load_downstream_interface_schema()


@lru_cache(maxsize=1)
def _schema_index() -> dict[str, tuple[dict[str, Any], ...]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for system_row in interface_schema()["systems"]:
        for api_module in system_row["api_modules"]:
            for schema in api_module["symbol_schemas"]:
                rows.setdefault(schema["name"], []).append({
                    "system_key": system_row["system_key"],
                    "module": api_module["module"],
                    "schema": schema,
                })
    return {name: tuple(values) for name, values in rows.items()}


def owners(symbol: str) -> tuple[str, ...]:
    """Return public owners without importing implementation modules."""
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("symbol must be non-empty text")
    current = catalog()
    direct = current.direct_source(symbol)
    ambiguous = current.ambiguous_sources(symbol)
    if direct is None and not ambiguous:
        return ()
    registered = current.owners(symbol)
    if registered:
        return registered
    return (direct,) if direct is not None else ambiguous

def search(query: str, *, limit: int = 50) -> tuple[ApiSymbolMatch, ...]:
    """Search the unified symbol index without importing implementations."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be non-empty text")
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be positive")
    needle = query.casefold()
    current = catalog()
    names = set(current.direct_symbol_sources) | set(current.ambiguous_symbol_sources)
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
    current = catalog()
    if current.direct_source(symbol) is None and not current.ambiguous_sources(symbol):
        return ()
    registered_rows = _schema_index().get(symbol, ())
    if registered_rows:
        return registered_rows

    source = current.direct_source(symbol)
    sources = (source,) if source is not None else current.ambiguous_sources(symbol)
    return tuple(
        {
            "system_key": None,
            "module": module_name,
            "schema": {
                "name": symbol,
                "kind": "python_export",
                "qualified_name": f"{module_name}.{symbol}",
            },
        }
        for module_name in sources
    )


@lru_cache(maxsize=None)
def resolve(symbol: str) -> Any:
    """Resolve one public symbol through the generated Product-level resolution index."""
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
            f"public owners={registered!r}; sources={ambiguous!r}"
            if registered
            else f"public symbol sources are ambiguous: {ambiguous!r}"
        )
        raise AttributeError(
            f"ambiguous Noetrium public symbol {symbol!r}; {hint}"
        )
    suggestions = get_close_matches(
        symbol,
        (*current.direct_symbol_sources, *current.ambiguous_symbol_sources),
        n=5,
        cutoff=0.55,
    )
    suffix = f"; did you mean {tuple(suggestions)!r}" if suggestions else ""
    raise AttributeError(f"unknown Noetrium public symbol: {symbol}{suffix}")

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
    "resolve",
    "owners",
    "search",
    "describe",
    "interface_schema",
)
