"""Read-only discovery of the generated downstream contract surface.

This module is a catalog/discovery API, not a runtime service locator. It only
maps a registered system identity to its generated typed facade module.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
from importlib.resources import files
from typing import Any


@dataclass(frozen=True, slots=True)
class DownstreamApiModule:
    module: str
    source: str
    symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DownstreamSystemSurface:
    system_key: str
    package_prefix: str
    authority: str
    owns: str
    must_not_own: str
    requires: tuple[str, ...]
    provides: tuple[str, ...]
    facade_module: str | None
    api_modules: tuple[DownstreamApiModule, ...]


@dataclass(frozen=True, slots=True)
class DownstreamCapabilityCatalog:
    schema: str
    topology_digest: str
    systems: tuple[DownstreamSystemSurface, ...]

    def system(self, system_key: str) -> DownstreamSystemSurface:
        for surface in self.systems:
            if surface.system_key == system_key:
                return surface
        raise KeyError(f"unknown downstream system surface: {system_key}")

    def facade(self, system_key: str) -> Any:
        """Import one generated typed facade after explicit caller selection."""
        surface = self.system(system_key)
        if surface.facade_module is None:
            raise LookupError(f"system has no public API exports: {system_key}")
        return importlib.import_module(surface.facade_module)


def _catalog_document() -> dict[str, Any]:
    resource = files("noetrium.contracts").joinpath(
        "downstream_capability_catalog.json"
    )
    document = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema") != "noetrium-downstream-contracts.v1":
        raise RuntimeError("invalid generated downstream capability catalog")
    return document


def load_downstream_capability_catalog() -> DownstreamCapabilityCatalog:
    document = _catalog_document()
    systems: list[DownstreamSystemSurface] = []
    for row in document["systems"]:
        modules = tuple(
            DownstreamApiModule(
                module=item["module"],
                source=item["source"],
                symbols=tuple(item["symbols"]),
            )
            for item in row["api_modules"]
        )
        systems.append(
            DownstreamSystemSurface(
                system_key=row["system_key"],
                package_prefix=row["package_prefix"],
                authority=row["authority"],
                owns=row["owns"],
                must_not_own=row["must_not_own"],
                requires=tuple(row["requires"]),
                provides=tuple(row["provides"]),
                facade_module=row["facade_module"],
                api_modules=modules,
            )
        )
    return DownstreamCapabilityCatalog(
        schema=document["schema"],
        topology_digest=document["topology_digest"],
        systems=tuple(systems),
    )


__all__ = [
    "DownstreamApiModule",
    "DownstreamCapabilityCatalog",
    "DownstreamSystemSurface",
    "load_downstream_capability_catalog",
]
