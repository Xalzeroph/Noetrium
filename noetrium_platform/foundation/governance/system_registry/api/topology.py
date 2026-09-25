from __future__ import annotations

from dataclasses import dataclass
import json
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from .contracts import (
    SYSTEM_PLANES,
    AuthorityDescriptor,
    DownstreamSurfaceMode,
    SystemDescriptor,
    SystemIdentity,
    SystemLayer,
    SystemNodeKind,
)


@dataclass(frozen=True, slots=True)
class _CatalogSemantics:
    authority: str
    must_not_own: str
    owns: str
    package_prefix: str
    parent: str | None
    shape: tuple[str, ...]
    requires: tuple[str, ...]
    provides: tuple[str, ...]
    components: tuple[str, ...]
    downstream_surface: DownstreamSurfaceMode
    node_kind: SystemNodeKind
    canonical_authority: str | None




@dataclass(frozen=True, slots=True)
class ComponentDescriptor:
    """Typed projection of one non-system bounded context/component."""

    key: str
    system: str
    parent: str
    package_prefix: str
    node_kind: SystemNodeKind
    canonical_authority: str | None
    owns: str
    must_not_own: str
    shape: tuple[str, ...]
    downstream_surface: DownstreamSurfaceMode
    requires: tuple[str, ...]
    provides: tuple[str, ...]
    internal_facets: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class TopologySourceAudit:
    """Deterministic runtime evidence that the catalog owns the source topology."""

    registered_packages: tuple[str, ...]
    discovered_standard_packages: tuple[str, ...]
    stale_registered_packages: tuple[str, ...]
    incomplete_registered_packages: tuple[str, ...]
    unregistered_standard_packages: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not (
            self.stale_registered_packages
            or self.incomplete_registered_packages
            or self.unregistered_standard_packages
        )


def _string_tuple(value: object, *, field: str, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise RuntimeError(f"invalid packaged catalog {field} for {key!r}")
    result = tuple(value)
    if len(result) != len(set(result)):
        raise RuntimeError(f"duplicate packaged catalog {field} for {key!r}")
    return result


def _package_prefix_exists(prefix: str) -> bool:
    """Check that catalog ownership points at a real source package/module."""

    root = Path(__file__).resolve().parents[5]
    candidate = root.joinpath(*prefix.split("."))
    return (
        candidate.is_dir()
        or candidate.with_suffix(".py").is_file()
        or (candidate / "__init__.py").is_file()
    )


def _parse_semantics(key: str, value: object) -> _CatalogSemantics:
    required = {
        "authority", "must_not_own", "owns", "package_prefix", "parent", "shape",
        "requires", "provides", "components",
    }
    optional = {"downstream_surface"}
    required |= {"node_kind", "canonical_authority"}
    if (
        not isinstance(value, dict)
        or not required.issubset(value)
        or set(value) - required - optional
    ):
        raise RuntimeError(f"invalid packaged catalog descriptor for {key!r}")
    text_fields = ("authority", "must_not_own", "owns", "package_prefix")
    if not all(isinstance(value[field], str) and value[field].strip() for field in text_fields):
        raise RuntimeError(f"invalid ownership semantics for {key!r}")
    shape = _string_tuple(value["shape"], field="shape", key=key)
    if any(plane not in SYSTEM_PLANES for plane in shape):
        raise RuntimeError(f"unsupported packaged system shape for {key!r}")
    parent = value["parent"]
    if parent is not None and not isinstance(parent, str):
        raise RuntimeError(f"invalid packaged catalog parent for {key!r}")
    normalized_parent = parent if isinstance(parent, str) else None
    try:
        downstream_surface = DownstreamSurfaceMode(value.get("downstream_surface", "public"))
        node_kind = SystemNodeKind(value["node_kind"])
    except ValueError as exc:
        raise RuntimeError(f"invalid catalog enum metadata for {key!r}") from exc
    canonical_authority = value["canonical_authority"]
    if canonical_authority is not None and (
        not isinstance(canonical_authority, str) or not canonical_authority.strip()
    ):
        raise RuntimeError(f"invalid canonical_authority for {key!r}")
    return _CatalogSemantics(
        authority=value["authority"],
        must_not_own=value["must_not_own"],
        owns=value["owns"],
        package_prefix=value["package_prefix"],
        parent=normalized_parent,
        shape=shape,
        requires=_string_tuple(value["requires"], field="requires", key=key),
        provides=_string_tuple(value["provides"], field="provides", key=key),
        components=_string_tuple(value["components"], field="components", key=key),
        downstream_surface=downstream_surface,
        node_kind=node_kind,
        canonical_authority=canonical_authority,
    )


@lru_cache(maxsize=1)
def _load_component_catalog() -> dict[str, dict[str, object]]:
    resource = files("noetrium_platform.foundation.governance.system_registry").joinpath("components.json")
    try:
        raw = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("cannot load packaged system component catalog") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("packaged system component catalog must be an object")
    return raw




@lru_cache(maxsize=1)
def component_catalog() -> tuple[ComponentDescriptor, ...]:
    """Return the canonical typed component catalog.

    Components are bounded contexts/facets owned by a registered system; they
    are intentionally not promoted to SystemIdentity nodes.
    """

    rows: list[ComponentDescriptor] = []
    for key, value in sorted(_load_component_catalog().items()):
        if not isinstance(value, dict):
            raise RuntimeError(f"invalid component descriptor for {key!r}")
        try:
            node_kind = SystemNodeKind(value["node_kind"])
            downstream_surface = DownstreamSurfaceMode(
                value.get("downstream_surface", "metadata_only")
            )
        except (KeyError, ValueError) as exc:
            raise RuntimeError(f"invalid component enum metadata for {key!r}") from exc
        facets_raw = value.get("internal_facets", [])
        if not isinstance(facets_raw, list):
            raise RuntimeError(f"invalid internal_facets for {key!r}")
        facets = tuple(
            str(row["key"])
            for row in facets_raw
            if isinstance(row, dict) and isinstance(row.get("key"), str)
        )
        rows.append(
            ComponentDescriptor(
                key=key,
                system=str(value["system"]),
                parent=str(value["parent"]),
                package_prefix=str(value["package_prefix"]),
                node_kind=node_kind,
                canonical_authority=(
                    str(value["canonical_authority"])
                    if value.get("canonical_authority") is not None else None
                ),
                owns=str(value["owns"]),
                must_not_own=str(value["must_not_own"]),
                shape=_string_tuple(value.get("shape", []), field="shape", key=key),
                downstream_surface=downstream_surface,
                requires=_string_tuple(value.get("requires", []), field="requires", key=key),
                provides=_string_tuple(value.get("provides", []), field="provides", key=key),
                internal_facets=facets,
            )
        )
    return tuple(rows)

@lru_cache(maxsize=1)
def _load_catalog_semantics() -> dict[str, _CatalogSemantics]:
    """Load and validate the single canonical recursive system catalog."""
    catalog_resource = files("noetrium_platform.foundation.governance.system_registry").joinpath("catalog.json")
    try:
        raw = json.loads(catalog_resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("cannot load packaged canonical system catalog") from exc
    if not isinstance(raw, dict) or not raw:
        raise RuntimeError("packaged canonical system catalog is not a non-empty object")

    result: dict[str, _CatalogSemantics] = {}
    seen: set[str] = set()
    for key, value in raw.items():
        if not isinstance(key, str):
            raise RuntimeError("packaged catalog keys must be strings")
        parts = tuple(part for part in key.split("/") if part)
        if not parts or "/".join(parts) != key:
            raise RuntimeError(f"invalid packaged catalog identity for {key!r}")
        semantics = _parse_semantics(key, value)
        if not _package_prefix_exists(semantics.package_prefix):
            raise RuntimeError(
                f"catalog package_prefix {semantics.package_prefix!r} for {key!r} "
                "does not resolve to a source package/module"
            )
        result[key] = semantics
        seen.add(key)

    known = set(result)
    for key, semantics in result.items():
        parent = semantics.parent
        if parent is not None and parent not in known:
            raise RuntimeError(
                f"catalog topology parent {parent!r} for {key!r} is not registered"
            )
        if parent == key:
            raise RuntimeError(f"catalog node {key!r} cannot parent itself")

    visiting: set[str] = set()
    visited: set[str] = set()

    def validate_parent_chain(key: str) -> None:
        if key in visited:
            return
        if key in visiting:
            raise RuntimeError(f"catalog topology parent cycle at {key!r}")
        visiting.add(key)
        parent = result[key].parent
        if parent is not None:
            validate_parent_chain(parent)
        visiting.remove(key)
        visited.add(key)

    for key in result:
        validate_parent_chain(key)

    direct_authorities = {
        key for key, semantics in result.items()
        if semantics.node_kind is SystemNodeKind.AUTHORITY
    }
    for key, semantics in result.items():
        canonical = semantics.canonical_authority
        if semantics.node_kind is SystemNodeKind.AUTHORITY and canonical != key:
            raise RuntimeError(f"authority node {key!r} must canonically own itself")
        if semantics.node_kind is not SystemNodeKind.AUTHORITY and canonical is not None:
            if canonical not in direct_authorities:
                raise RuntimeError(
                    f"canonical authority {canonical!r} for {key!r} is not a direct authority"
                )
    capability_owners: dict[str, str] = {}
    for key, semantics in result.items():
        for dependency in semantics.requires:
            if dependency not in known:
                raise RuntimeError(
                    f"catalog dependency {dependency!r} for {key!r} is not registered"
                )
            if dependency == key:
                raise RuntimeError(f"catalog node {key!r} cannot require itself")
        component_catalog = _load_component_catalog()
        for component in semantics.components:
            if component not in component_catalog:
                raise RuntimeError(
                    f"catalog component {component!r} for {key!r} is not declared in components.json"
                )
            owner = component_catalog[component].get("system")
            if owner != key:
                raise RuntimeError(
                    f"catalog component {component!r} is owned by {owner!r}, not {key!r}"
                )
        for capability in semantics.provides:
            previous = capability_owners.get(capability)
            if previous is not None:
                raise RuntimeError(
                    f"catalog capability {capability!r} is provided by both "
                    f"{previous!r} and {key!r}"
                )
            capability_owners[capability] = key
    return result


def _descriptor_from_catalog(key: str, semantics: _CatalogSemantics) -> SystemDescriptor:
    parts = key.split("/")
    return SystemDescriptor(
        identity=SystemIdentity(parts[0], tuple(parts[1:])),
        layer=SystemLayer(parts[0]),
        package_prefix=semantics.package_prefix,
        authorities=(AuthorityDescriptor(semantics.authority),)
        if semantics.node_kind is SystemNodeKind.AUTHORITY else (),
        owns=semantics.owns,
        must_not_own=semantics.must_not_own,
        shape=semantics.shape,
        requires=semantics.requires,
        provides=semantics.provides,
        components=semantics.components,
        downstream_surface=semantics.downstream_surface,
        node_kind=semantics.node_kind,
        topology_parent_key=semantics.parent,
        canonical_authority_key=semantics.canonical_authority,
    )


SYSTEM_CATALOG: tuple[SystemDescriptor, ...] = tuple(
    _descriptor_from_catalog(key, semantics)
    for key, semantics in _load_catalog_semantics().items()
)


def system_catalog() -> tuple[SystemDescriptor, ...]:
    """Return the canonical recursive platform system tree."""

    return SYSTEM_CATALOG


def _plane_exists(package: Path, plane: str) -> bool:
    return (package / plane / "__init__.py").is_file()


def _system_shape_candidates(
    source_root: Path,
    *,
    registered_packages: tuple[str, ...],
) -> tuple[str, ...]:
    """Project explicit registry ownership; filesystem shape never creates a system."""
    del source_root
    return registered_packages


def audit_system_topology_source(
    root: Path | None = None,
    *,
    descriptors: tuple[SystemDescriptor, ...] | None = None,
) -> TopologySourceAudit:
    """Validate explicitly registered topology against source.

    Source package shape is never a topology declaration. Only catalog.json may
    create a system owner; components.json carries non-system semantic facets.
    """

    source_root = (Path(root) if root is not None else Path(__file__).resolve().parents[5]).resolve()
    catalog = SYSTEM_CATALOG if descriptors is None else tuple(descriptors)
    registered = tuple(sorted({descriptor.package_prefix for descriptor in catalog}))
    stale: list[str] = []
    incomplete: list[str] = []
    canonical_catalog = (
        source_root / "noetrium_platform/foundation/governance/system_registry/catalog.json"
    )
    if canonical_catalog.is_file():
        for descriptor in catalog:
            package = source_root.joinpath(*descriptor.package_prefix.split("."))
            if not (package / "__init__.py").is_file():
                stale.append(descriptor.package_prefix)
                continue
            missing = tuple(plane for plane in descriptor.shape if not _plane_exists(package, plane))
            if missing:
                incomplete.append(
                    f"{descriptor.package_prefix} (missing: {', '.join(missing)})"
                )
    discovered_tuple = _system_shape_candidates(
        source_root, registered_packages=registered
    )
    return TopologySourceAudit(
        registered_packages=registered,
        discovered_standard_packages=discovered_tuple,
        stale_registered_packages=tuple(sorted(stale)),
        incomplete_registered_packages=tuple(sorted(incomplete)),
        unregistered_standard_packages=(),
    )


__all__ = ["ComponentDescriptor", "SYSTEM_CATALOG", "TopologySourceAudit", "audit_system_topology_source", "component_catalog", "system_catalog"]
