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
    authority: str | None
    canonical_authority: str | None
    node_kind: str
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
    entrypoint: str
    topology_digest: str
    catalog_digest: str
    symbol_index: dict[str, tuple[str, ...]]
    direct_symbol_sources: dict[str, str]
    ambiguous_symbol_sources: dict[str, tuple[str, ...]]
    systems: tuple[DownstreamSystemSurface, ...]

    def system(self, system_key: str) -> DownstreamSystemSurface:
        for surface in self.systems:
            if surface.system_key == system_key:
                return surface
        raise KeyError(f"unknown downstream system surface: {system_key}")

    def owners(self, symbol: str) -> tuple[str, ...]:
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("symbol must be a non-empty string")
        return self.symbol_index.get(symbol, ())

    def direct_source(self, symbol: str) -> str | None:
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("symbol must be a non-empty string")
        return self.direct_symbol_sources.get(symbol)

    def ambiguous_sources(self, symbol: str) -> tuple[str, ...]:
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("symbol must be a non-empty string")
        return self.ambiguous_symbol_sources.get(symbol, ())

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
    try:
        document = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DownstreamCatalogIntegrityError(
            "unable to read generated downstream interface schema"
        ) from exc
    if not isinstance(document, dict):
        raise DownstreamCatalogIntegrityError(
            "generated downstream interface schema must be an object"
        )
    return validate_downstream_interface_schema(document)


def validate_downstream_interface_schema(
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate generated symbol schemas against the verified capability catalog."""
    required_keys = {
        "schema",
        "generator",
        "topology_digest",
        "interface_schema",
        "authoring_inspection",
        "public_api",
        "reachable_dsl",
        "systems",
        "interface_digest",
    }
    if not isinstance(document, Mapping) or set(document) != required_keys:
        raise DownstreamCatalogIntegrityError(
            "generated downstream interface schema has an invalid shape"
        )
    if document["schema"] != "noetrium-interface-catalog.v1":
        raise DownstreamCatalogIntegrityError("invalid generated downstream interface schema")
    if document["generator"] != "scripts/generate_interface_schemas.py":
        raise DownstreamCatalogIntegrityError("unexpected downstream interface schema generator")
    interface_digest = _require_digest(document["interface_digest"], "interface_digest")
    unsigned_document = dict(document)
    unsigned_document.pop("interface_digest")
    if interface_digest != _digest(unsigned_document):
        raise DownstreamCatalogIntegrityError("downstream interface schema digest mismatch")

    catalog = load_downstream_capability_catalog()
    topology_digest = _require_digest(document["topology_digest"], "topology_digest")
    if topology_digest != catalog.topology_digest:
        raise DownstreamCatalogIntegrityError(
            "downstream interface schema does not match capability catalog topology"
        )
    inspection = document["authoring_inspection"]
    public_api = document["public_api"]
    reachable_dsl = document["reachable_dsl"]
    if not isinstance(inspection, Mapping):
        raise DownstreamCatalogIntegrityError("invalid downstream authoring inspection descriptor")
    if not isinstance(public_api, Mapping) or set(public_api) != {
        "module", "source", "symbols", "symbol_schemas"
    }:
        raise DownstreamCatalogIntegrityError("invalid root public API descriptor")
    if public_api.get("module") != catalog.entrypoint:
        raise DownstreamCatalogIntegrityError("root public API entrypoint drifted")
    public_symbols = _require_string_tuple(public_api.get("symbols"), "public_api.symbols")
    schemas = public_api.get("symbol_schemas")
    if not isinstance(schemas, list):
        raise DownstreamCatalogIntegrityError("public_api.symbol_schemas must be a list")
    schema_names = tuple(
        schema.get("name") if isinstance(schema, Mapping) else None
        for schema in schemas
    )
    if schema_names != public_symbols:
        raise DownstreamCatalogIntegrityError("root public API schema symbols drifted")
    if inspection.get("entrypoint") != catalog.entrypoint:
        raise DownstreamCatalogIntegrityError("downstream authoring inspection entrypoint drifted")
    inspection_roots = _require_string_tuple(
        inspection.get("public_roots"),
        "authoring_inspection.public_roots",
    )
    if inspection_roots != public_symbols:
        raise DownstreamCatalogIntegrityError("authoring inspection roots drifted")
    for field in ("authoring_root", "portfolio_type", "runtime_root", "project_opener"):
        value = inspection.get(field)
        if not isinstance(value, str) or value not in public_symbols:
            raise DownstreamCatalogIntegrityError(
                f"authoring inspection {field} is not a root public symbol"
            )
    if not isinstance(reachable_dsl, Mapping) or set(reachable_dsl) != {
        "program", "method", "memory", "runtime"
    }:
        raise DownstreamCatalogIntegrityError("invalid reachable DSL schema set")
    for name, schema in reachable_dsl.items():
        if (
            not isinstance(schema, Mapping)
            or schema.get("schema_id") != "noetrium.interface-schema"
            or schema.get("schema_version") != "1"
            or schema.get("kind") != "class"
        ):
            raise DownstreamCatalogIntegrityError(
                f"invalid reachable DSL schema: {name}"
            )

    descriptor = document["interface_schema"]
    if (
        not isinstance(descriptor, Mapping)
        or descriptor.get("schema_id") != "noetrium.interface-schema"
        or descriptor.get("schema_version") != "1"
    ):
        raise DownstreamCatalogIntegrityError("invalid downstream interface schema descriptor")

    rows = document["systems"]
    if not isinstance(rows, list):
        raise DownstreamCatalogIntegrityError("interface schema systems must be a list")
    catalog_by_key = {surface.system_key: surface for surface in catalog.systems}
    expected_system_keys = set(catalog_by_key)
    seen_system_keys: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "system_key",
            "package_prefix",
            "facade_module",
            "api_modules",
        }:
            raise DownstreamCatalogIntegrityError("interface schema system has an invalid shape")
        system_key = row["system_key"]
        surface = catalog_by_key.get(system_key)
        if surface is None:
            raise DownstreamCatalogIntegrityError(
                f"interface schema contains unknown system: {system_key}"
            )
        if system_key in seen_system_keys:
            raise DownstreamCatalogIntegrityError(
                f"duplicate interface schema system: {system_key}"
            )
        seen_system_keys.add(system_key)
        if (
            row["package_prefix"] != surface.package_prefix
            or row["facade_module"] != surface.facade_module
        ):
            raise DownstreamCatalogIntegrityError(
                f"interface schema metadata disagrees with catalog: {system_key}"
            )
        api_rows = row["api_modules"]
        if not isinstance(api_rows, list):
            raise DownstreamCatalogIntegrityError(
                f"{system_key}.api_modules must be a list"
            )
        expected_modules = [
            {
                "module": api.module,
                "source": api.source,
                "symbols": list(api.symbols),
            }
            for api in surface.api_modules
        ]
        if [
            {
                "module": api.get("module"),
                "source": api.get("source"),
                "symbols": api.get("symbols"),
            }
            for api in api_rows
            if isinstance(api, Mapping)
        ] != expected_modules or len(api_rows) != len(expected_modules):
            raise DownstreamCatalogIntegrityError(
                f"interface schema API surface disagrees with catalog: {system_key}"
            )
        for api, expected_api in zip(api_rows, expected_modules):
            schemas = api.get("symbol_schemas")
            if not isinstance(schemas, list):
                raise DownstreamCatalogIntegrityError(
                    f"{system_key}.{api['module']}.symbol_schemas must be a list"
                )
            names: list[str] = []
            for schema in schemas:
                if (
                    not isinstance(schema, Mapping)
                    or not isinstance(schema.get("name"), str)
                    or schema.get("schema_id") != "noetrium.interface-schema"
                    or schema.get("schema_version") != "1"
                ):
                    raise DownstreamCatalogIntegrityError(
                        f"invalid symbol schema: {system_key}.{api['module']}"
                    )
                names.append(schema["name"])
            if tuple(names) != tuple(expected_api["symbols"]):
                raise DownstreamCatalogIntegrityError(
                    f"interface symbol set disagrees with catalog: {system_key}.{api['module']}"
                )
    if seen_system_keys != expected_system_keys:
        raise DownstreamCatalogIntegrityError(
            "downstream interface schema does not cover the capability catalog exactly"
        )
    return dict(document)


def find_downstream_symbol_schema(
    system_key: str,
    module: str,
    symbol: str,
) -> dict[str, Any]:
    """Find one public symbol schema without importing implementation modules."""
    document = load_downstream_interface_schema()
    if module == "noetrium.api":
        for schema in document["public_api"]["symbol_schemas"]:
            if schema["name"] == symbol:
                return schema
        raise KeyError(f"unknown public symbol schema: {module}.{symbol}")
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
) -> tuple[
    dict[str, Any],
    str,
    str,
    Mapping[str, Any],
    Mapping[str, Any],
    Mapping[str, Any],
    list[Any],
]:
    required_keys = {
        "schema",
        "generator",
        "entrypoint",
        "topology_digest",
        "symbol_index",
        "direct_symbol_sources",
        "ambiguous_symbol_sources",
        "systems",
        "catalog_digest",
    }
    if not isinstance(document, Mapping) or set(document) != required_keys:
        raise DownstreamCatalogIntegrityError(
            "generated downstream capability catalog has an invalid shape"
        )
    if document["schema"] != "noetrium-downstream-contracts.v5":
        raise DownstreamCatalogIntegrityError("invalid generated downstream capability catalog schema")
    if document["entrypoint"] != "noetrium.api":
        raise DownstreamCatalogIntegrityError("invalid unified downstream entrypoint")
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
    symbol_index = document["symbol_index"]
    if not isinstance(symbol_index, Mapping):
        raise DownstreamCatalogIntegrityError("catalog symbol_index must be an object")
    direct_symbol_sources = document["direct_symbol_sources"]
    ambiguous_symbol_sources = document["ambiguous_symbol_sources"]
    if not isinstance(direct_symbol_sources, Mapping):
        raise DownstreamCatalogIntegrityError(
            "catalog direct_symbol_sources must be an object"
        )
    if not isinstance(ambiguous_symbol_sources, Mapping):
        raise DownstreamCatalogIntegrityError(
            "catalog ambiguous_symbol_sources must be an object"
        )
    rows = document["systems"]
    if not isinstance(rows, list):
        raise DownstreamCatalogIntegrityError("catalog systems must be a list")
    return (
        registry,
        topology_digest,
        catalog_digest,
        symbol_index,
        direct_symbol_sources,
        ambiguous_symbol_sources,
        rows,
    )


def _validate_catalog_surface(
    row: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> DownstreamSystemSurface:
    expected_keys = {
        "system_key",
        "package_prefix",
        "authority",
        "canonical_authority",
        "node_kind",
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
        "authority": (descriptor.get("authority") if descriptor.get("node_kind") == "authority" else None),
        "canonical_authority": descriptor.get("canonical_authority"),
        "node_kind": descriptor.get("node_kind"),
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
    for field in ("package_prefix", "node_kind", "owns", "must_not_own", "downstream_surface"):
        if not isinstance(row[field], str):
            raise DownstreamCatalogIntegrityError(f"{system_key}.{field} must be a string")
    if row["authority"] is not None and not isinstance(row["authority"], str):
        raise DownstreamCatalogIntegrityError(f"{system_key}.authority must be string or null")
    if row["canonical_authority"] is not None and not isinstance(row["canonical_authority"], str):
        raise DownstreamCatalogIntegrityError(f"{system_key}.canonical_authority must be string or null")
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
        canonical_authority=row["canonical_authority"],
        node_kind=row["node_kind"],
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
    (
        registry,
        topology_digest,
        catalog_digest,
        raw_symbol_index,
        raw_direct_sources,
        raw_ambiguous_sources,
        rows,
    ) = _validate_catalog_header(document)
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
    expected_index: dict[str, list[str]] = {}
    for surface in surfaces:
        for api in surface.api_modules:
            for symbol in api.symbols:
                owners = expected_index.setdefault(symbol, [])
                if surface.system_key not in owners:
                    owners.append(surface.system_key)
    expected_index = {
        symbol: sorted(owners)
        for symbol, owners in sorted(expected_index.items())
    }
    normalized_index: dict[str, list[str]] = {}
    for symbol, owners in raw_symbol_index.items():
        if not isinstance(symbol, str) or not symbol:
            raise DownstreamCatalogIntegrityError("catalog symbol_index keys must be non-empty strings")
        if not isinstance(owners, list) or any(
            not isinstance(owner, str) or not owner for owner in owners
        ):
            raise DownstreamCatalogIntegrityError(
                f"catalog symbol_index owners must be string lists: {symbol}"
            )
        if len(owners) != len(set(owners)):
            raise DownstreamCatalogIntegrityError(
                f"catalog symbol_index contains duplicate owners: {symbol}"
            )
        normalized_index[symbol] = sorted(owners)
    if normalized_index != expected_index:
        raise DownstreamCatalogIntegrityError(
            "catalog symbol_index does not match generated system surfaces"
        )

    direct_sources: dict[str, str] = {}
    for symbol, module in raw_direct_sources.items():
        if (
            not isinstance(symbol, str)
            or not symbol
            or not isinstance(module, str)
            or not module
        ):
            raise DownstreamCatalogIntegrityError(
                "catalog direct_symbol_sources must map non-empty strings"
            )
        direct_sources[symbol] = module

    ambiguous_sources: dict[str, tuple[str, ...]] = {}
    for symbol, modules in raw_ambiguous_sources.items():
        if not isinstance(symbol, str) or not symbol:
            raise DownstreamCatalogIntegrityError(
                "catalog ambiguous_symbol_sources keys must be non-empty strings"
            )
        values = _require_string_tuple(
            modules, f"ambiguous_symbol_sources.{symbol}"
        )
        if len(values) < 2:
            raise DownstreamCatalogIntegrityError(
                f"ambiguous symbol must have at least two sources: {symbol}"
            )
        ambiguous_sources[symbol] = values

    overlap = set(direct_sources) & set(ambiguous_sources)
    if overlap:
        raise DownstreamCatalogIntegrityError(
            f"symbol cannot be both direct and ambiguous: {sorted(overlap)!r}"
        )
    return DownstreamCapabilityCatalog(
        schema=document["schema"],
        entrypoint=document["entrypoint"],
        topology_digest=topology_digest,
        catalog_digest=catalog_digest,
        symbol_index={symbol: tuple(owners) for symbol, owners in expected_index.items()},
        direct_symbol_sources=dict(sorted(direct_sources.items())),
        ambiguous_symbol_sources=dict(sorted(ambiguous_sources.items())),
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
    "validate_downstream_interface_schema",
    "validate_downstream_capability_catalog",
]
