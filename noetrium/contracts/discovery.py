"""Read-only discovery of the generated downstream contract surface.

This module is a catalog/discovery API, not a runtime service locator. It only
maps a registered system identity to its generated typed facade module.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
from importlib.resources import files
from collections.abc import Mapping
from typing import Any


class DownstreamCatalogIntegrityError(ValueError):
    """Raised when generated downstream metadata is stale or tampered."""


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
    downstream_surface: str
    facade_module: str | None
    interface_digest: str
    api_modules: tuple[DownstreamApiModule, ...]


@dataclass(frozen=True, slots=True)
class DownstreamCapabilityCatalog:
    schema: str
    topology_digest: str
    catalog_digest: str
    systems: tuple[DownstreamSystemSurface, ...]

    def system(self, system_key: str) -> DownstreamSystemSurface:
        for surface in self.systems:
            if surface.system_key == system_key:
                return surface
        raise KeyError(f"unknown downstream system surface: {system_key}")

    def providers(self, capability: str) -> tuple[DownstreamSystemSurface, ...]:
        """Return registered providers for a capability, without resolving one."""
        if not isinstance(capability, str) or not capability:
            raise ValueError("capability must be a non-empty string")
        return tuple(surface for surface in self.systems if capability in surface.provides)

    def facade(self, system_key: str) -> Any:
        """Import one generated typed facade after explicit caller selection."""
        surface = self.system(system_key)
        if surface.facade_module is None:
            raise LookupError(f"system has no public API exports: {system_key}")
        return importlib.import_module(surface.facade_module)


def load_downstream_interface_schema() -> dict[str, Any]:
    """Load the generated schema for every public downstream interface."""
    resource = files("noetrium.contracts").joinpath("interface_schema.json")
    document = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema") != "noetrium-interface-catalog.v1":
        raise RuntimeError("invalid generated downstream interface schema")
    return document


def find_downstream_symbol_schema(
    system_key: str,
    module: str,
    symbol: str,
) -> dict[str, Any]:
    """Find one public symbol schema without importing implementation modules."""
    document = load_downstream_interface_schema()
    for system in document["systems"]:
        if system["system_key"] != system_key:
            continue
        for api in system["api_modules"]:
            if api["module"] != module:
                continue
            for schema in api["symbol_schemas"]:
                if schema["name"] == symbol:
                    return schema
            raise KeyError(f"unknown public symbol schema: {module}.{symbol}")
        raise KeyError(f"unknown public API module: {module}")
    raise KeyError(f"unknown downstream system surface: {system_key}")


def _catalog_document() -> dict[str, Any]:
    resource = files("noetrium.contracts").joinpath(
        "downstream_capability_catalog.json"
    )
    try:
        document = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DownstreamCatalogIntegrityError(
            "unable to read generated downstream capability catalog"
        ) from exc
    if not isinstance(document, dict):
        raise DownstreamCatalogIntegrityError(
            "generated downstream capability catalog must be an object"
        )
    return document


def _digest(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _require_digest(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DownstreamCatalogIntegrityError(f"{field} must be a lowercase sha256 digest")
    return value


def _require_string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DownstreamCatalogIntegrityError(f"{field} must be a list of strings")
    result = tuple(value)
    if len(result) != len(set(result)):
        raise DownstreamCatalogIntegrityError(f"{field} must not contain duplicates")
    return result


def _registry_document() -> dict[str, Any]:
    resource = files(
        "noetrium_platform.foundation.governance.system_registry"
    ).joinpath("catalog.json")
    try:
        registry = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DownstreamCatalogIntegrityError(
            "unable to read canonical system registry"
        ) from exc
    if not isinstance(registry, dict) or any(
        not isinstance(key, str) or not isinstance(value, Mapping)
        for key, value in registry.items()
    ):
        raise DownstreamCatalogIntegrityError(
            "canonical system registry must map string keys to objects"
        )
    return registry


def _validate_catalog_header(
    document: Mapping[str, Any],
) -> tuple[dict[str, Any], str, str, list[Any]]:
    required_keys = {
        "schema",
        "generator",
        "topology_digest",
        "systems",
        "catalog_digest",
    }
    if not isinstance(document, Mapping) or set(document) != required_keys:
        raise DownstreamCatalogIntegrityError(
            "generated downstream capability catalog has an invalid shape"
        )
    if document["schema"] != "noetrium-downstream-contracts.v1":
        raise DownstreamCatalogIntegrityError("invalid generated downstream capability catalog schema")
    if document["generator"] != "scripts/generate_downstream_contracts.py":
        raise DownstreamCatalogIntegrityError("unexpected downstream catalog generator")
    registry = _registry_document()
    topology_digest = _require_digest(document["topology_digest"], "topology_digest")
    if topology_digest != _digest(registry):
        raise DownstreamCatalogIntegrityError(
            "downstream capability catalog does not match canonical system registry"
        )
    catalog_digest = _require_digest(document["catalog_digest"], "catalog_digest")
    unsigned_document = dict(document)
    unsigned_document.pop("catalog_digest")
    if catalog_digest != _digest(unsigned_document):
        raise DownstreamCatalogIntegrityError("downstream capability catalog digest mismatch")
    rows = document["systems"]
    if not isinstance(rows, list):
        raise DownstreamCatalogIntegrityError("catalog systems must be a list")
    return registry, topology_digest, catalog_digest, rows


def _validate_catalog_surface(
    row: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> DownstreamSystemSurface:
    expected_keys = {
        "system_key",
        "package_prefix",
        "authority",
        "owns",
        "must_not_own",
        "requires",
        "provides",
        "downstream_surface",
        "facade_module",
        "api_modules",
        "interface_digest",
    }
    if not isinstance(row, Mapping) or set(row) != expected_keys:
        raise DownstreamCatalogIntegrityError("catalog system surface has an invalid shape")
    system_key = row["system_key"]
    if not isinstance(system_key, str) or not system_key:
        raise DownstreamCatalogIntegrityError("catalog system_key must be a non-empty string")
    descriptor = registry.get(system_key)
    if not isinstance(descriptor, Mapping):
        raise DownstreamCatalogIntegrityError(
            f"catalog contains unknown system surface: {system_key}"
        )
    expected_metadata = {
        "package_prefix": descriptor.get("package_prefix"),
        "authority": descriptor.get("authority"),
        "owns": descriptor.get("owns"),
        "must_not_own": descriptor.get("must_not_own"),
        "requires": descriptor.get("requires"),
        "provides": descriptor.get("provides"),
        "downstream_surface": descriptor.get("downstream_surface", "public"),
    }
    if any(row[field] != value for field, value in expected_metadata.items()):
        raise DownstreamCatalogIntegrityError(
            f"catalog metadata disagrees with registry: {system_key}"
        )
    for field in ("package_prefix", "authority", "owns", "must_not_own", "downstream_surface"):
        if not isinstance(row[field], str):
            raise DownstreamCatalogIntegrityError(f"{system_key}.{field} must be a string")
    requires = _require_string_tuple(row["requires"], f"{system_key}.requires")
    provides = _require_string_tuple(row["provides"], f"{system_key}.provides")
    facade_module = row["facade_module"]
    if facade_module is not None and not isinstance(facade_module, str):
        raise DownstreamCatalogIntegrityError(f"{system_key}.facade_module must be string or null")
    return _validate_catalog_surface_modules(row, system_key, requires, provides, facade_module)


def _validate_catalog_surface_modules(
    row: Mapping[str, Any],
    system_key: str,
    requires: tuple[str, ...],
    provides: tuple[str, ...],
    facade_module: str | None,
) -> DownstreamSystemSurface:
    api_rows = row["api_modules"]
    if not isinstance(api_rows, list):
        raise DownstreamCatalogIntegrityError(f"{system_key}.api_modules must be a list")
    api_modules: list[DownstreamApiModule] = []
    seen_modules: set[str] = set()
    for api in api_rows:
        if not isinstance(api, Mapping) or set(api) != {"module", "source", "symbols"}:
            raise DownstreamCatalogIntegrityError(f"{system_key} has an invalid API module")
        module = api["module"]
        source = api["source"]
        if (
            not isinstance(module, str)
            or not isinstance(source, str)
            or not module
            or not source
        ):
            raise DownstreamCatalogIntegrityError(f"{system_key} API module names must be strings")
        if module in seen_modules:
            raise DownstreamCatalogIntegrityError(f"duplicate API module: {system_key}.{module}")
        seen_modules.add(module)
        symbols = _require_string_tuple(api["symbols"], f"{system_key}.{module}.symbols")
        api_modules.append(DownstreamApiModule(module, source, symbols))

    interface_digest = _require_digest(
        row["interface_digest"], f"{system_key}.interface_digest"
    )
    unsigned_row = dict(row)
    unsigned_row.pop("interface_digest")
    if interface_digest != _digest(unsigned_row):
        raise DownstreamCatalogIntegrityError(
            f"downstream interface digest mismatch: {system_key}"
        )
    return DownstreamSystemSurface(
        system_key=system_key,
        package_prefix=row["package_prefix"],
        authority=row["authority"],
        owns=row["owns"],
        must_not_own=row["must_not_own"],
        requires=requires,
        provides=provides,
        downstream_surface=row["downstream_surface"],
        facade_module=facade_module,
        interface_digest=interface_digest,
        api_modules=tuple(api_modules),
    )


def validate_downstream_capability_catalog(
    document: Mapping[str, Any],
) -> DownstreamCapabilityCatalog:
    """Validate and materialize generated metadata against the live registry.

    This is a data validation boundary. It never imports a provider and never
    selects a runtime authority.
    """
    registry, topology_digest, catalog_digest, rows = _validate_catalog_header(document)
    surfaces: list[DownstreamSystemSurface] = []
    seen_keys: set[str] = set()
    for row in rows:
        surface = _validate_catalog_surface(row, registry)
        if surface.system_key in seen_keys:
            raise DownstreamCatalogIntegrityError(
                f"duplicate catalog system surface: {surface.system_key}"
            )
        seen_keys.add(surface.system_key)
        surfaces.append(surface)
    if seen_keys != set(registry):
        raise DownstreamCatalogIntegrityError(
            "downstream capability catalog does not cover the canonical registry exactly"
        )
    return DownstreamCapabilityCatalog(
        schema=document["schema"],
        topology_digest=topology_digest,
        catalog_digest=catalog_digest,
        systems=tuple(surfaces),
    )


def load_downstream_capability_catalog() -> DownstreamCapabilityCatalog:
    return validate_downstream_capability_catalog(_catalog_document())


__all__ = [
    "DownstreamApiModule",
    "DownstreamCapabilityCatalog",
    "DownstreamCatalogIntegrityError",
    "DownstreamSystemSurface",
    "find_downstream_symbol_schema",
    "load_downstream_capability_catalog",
    "load_downstream_interface_schema",
    "validate_downstream_capability_catalog",
]
