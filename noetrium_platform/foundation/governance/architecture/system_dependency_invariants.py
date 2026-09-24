from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.foundation.governance.system_registry.api import (
    SystemDescriptor,
    layer_hierarchy,
    system_catalog,
)

from .import_graph import ImportEdge, scan_imports
from .source_scan import SourceInvariantViolation, violation


@dataclass(frozen=True, slots=True)
class LayerDependencyFinding:
    kind: str
    path: str
    line: int
    source_module: str
    target_module: str
    source_system: str | None = None
    source_layer: str | None = None
    target_system: str | None = None
    target_layer: str | None = None
    required_module: str | None = None


def _same_or_child(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _owner_for_module(
    descriptors: tuple[SystemDescriptor, ...],
    module: str,
) -> SystemDescriptor | None:
    candidates = tuple(
        row
        for row in descriptors
        if _same_or_child(module, row.package_prefix)
    )
    return max(candidates, key=lambda row: len(row.package_prefix)) if candidates else None


def _topology_root_systems(
    descriptors: tuple[SystemDescriptor, ...],
) -> dict[str, str]:
    """Resolve every registered node to its explicit topology root.

    Identity path shape is not topology authority. A node such as operator can
    be a direct child of research_os even when its identity has no subsystem
    path.
    """

    by_key = {row.identity.key: row for row in descriptors}
    result: dict[str, str] = {}
    for key, row in by_key.items():
        current = row
        seen: set[str] = set()
        while current.parent_key is not None:
            if current.identity.key in seen:
                raise RuntimeError(f"catalog topology parent cycle at {key!r}")
            seen.add(current.identity.key)
            try:
                current = by_key[current.parent_key]
            except KeyError as exc:
                raise RuntimeError(
                    f"catalog topology parent {current.parent_key!r} for {key!r} is not registered"
                ) from exc
        result[key] = current.identity.key
    return result


def _root_system_prefixes(
    descriptors: tuple[SystemDescriptor, ...],
    topology_roots: dict[str, str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in descriptors:
        system_id = topology_roots[row.identity.key]
        current = result.get(system_id)
        if current is None or len(row.package_prefix) < len(current):
            result[system_id] = row.package_prefix
    return result


def _declared_dependency_covers(dependency: str, target_key: str) -> bool:
    return target_key == dependency or target_key.startswith(dependency + "/")


def layer_dependency_findings(
    root: Path,
    *,
    edges: tuple[ImportEdge, ...] | None = None,
) -> tuple[LayerDependencyFinding, ...]:
    root = Path(root).resolve()
    descriptors = system_catalog()
    hierarchy = layer_hierarchy()
    layers = {row.layer_id: row for row in hierarchy.layers}
    system_layer = {
        system_id: row.layer_id
        for row in hierarchy.layers
        for system_id in row.members
    }
    global_systems = set(hierarchy.global_systems)
    sideplanes = {
        row.system_id: row
        for row in hierarchy.sideplanes
    }
    sideplane_systems = set(sideplanes)
    topology_roots = _topology_root_systems(descriptors)
    catalog_systems = set(topology_roots.values())
    declared_systems = set(system_layer) | global_systems | sideplane_systems
    if declared_systems != catalog_systems:
        missing = sorted(catalog_systems - declared_systems)
        extra = sorted(declared_systems - catalog_systems)
        raise RuntimeError(
            f"layer hierarchy membership mismatch missing={missing} extra={extra}"
        )

    root_prefixes = _root_system_prefixes(descriptors, topology_roots)
    facade_to_layer = {
        row.facade_module: row.layer_id
        for row in hierarchy.layers
    }
    composition_to_layer = {
        row.composition_prefix: row.layer_id
        for row in hierarchy.layers
        if row.composition_prefix is not None
    }
    layer_order = {
        row.layer_id: index
        for index, row in enumerate(hierarchy.layers)
    }

    def facade_layer(module: str) -> str | None:
        return facade_to_layer.get(module)

    def facade_child_layer(module: str) -> str | None:
        for facade, layer_id in facade_to_layer.items():
            if module.startswith(facade + "."):
                return layer_id
        return None

    def composition_layer(module: str) -> str | None:
        for prefix, layer_id in composition_to_layer.items():
            assert prefix is not None
            if _same_or_child(module, prefix):
                return layer_id
        return None

    findings: list[LayerDependencyFinding] = []

    def add(
        kind: str,
        edge: ImportEdge,
        *,
        source_system: str | None = None,
        source_layer: str | None = None,
        target_system: str | None = None,
        target_layer: str | None = None,
        required_module: str | None = None,
    ) -> None:
        findings.append(
            LayerDependencyFinding(
                kind=kind,
                path=edge.path,
                line=edge.line,
                source_module=edge.source_module,
                target_module=edge.target_module,
                source_system=source_system,
                source_layer=source_layer,
                target_system=target_system,
                target_layer=target_layer,
                required_module=required_module,
            )
        )

    for edge in edges or scan_imports(root, package_roots=("noetrium_platform",)):
        source_module = edge.source_module
        target_module = edge.target_module

        if hierarchy.is_global_contract(target_module):
            continue
        if _same_or_child(source_module, hierarchy.application_composition_prefix):
            continue

        source = _owner_for_module(descriptors, source_module)
        target = _owner_for_module(descriptors, target_module)
        source_system = (
            None if source is None else topology_roots[source.identity.key]
        )
        target_system = (
            None if target is None else topology_roots[target.identity.key]
        )

        if source_system is not None and source_system == target_system:
            continue

        # Global systems are below the regular hierarchy. Their immutable
        # contracts were already accepted above by is_global_contract().
        if source_system in global_systems:
            if target_system is not None and target_system not in global_systems:
                add(
                    "global_system_reverse_dependency",
                    edge,
                    source_system=source_system,
                    target_system=target_system,
                    target_layer=system_layer.get(target_system),
                )
            continue

        # Regular systems may reference only explicitly whitelisted global
        # contracts, never arbitrary Kernel/Platform internals.
        if target_system in global_systems:
            add(
                "global_system_internal_penetration",
                edge,
                source_system=source_system,
                source_layer=(
                    system_layer.get(source_system)
                    if source_system is not None
                    else None
                ),
                target_system=target_system,
                required_module="global_contract_prefixes",
            )
            continue

        if source_system in sideplane_systems:
            descriptor = sideplanes[source_system]
            required = layers[descriptor.base_layer_id].facade_module
            if target_module == required:
                continue
            add(
                "sideplane_illegal_dependency",
                edge,
                source_system=source_system,
                source_layer=f"sideplane:{descriptor.sideplane_id}",
                target_system=target_system,
                target_layer=(
                    system_layer.get(target_system)
                    if target_system is not None
                    else None
                ),
                required_module=required,
            )
            continue

        if target_system in sideplane_systems:
            descriptor = sideplanes[target_system]
            add(
                "direct_sideplane_dependency",
                edge,
                source_system=source_system,
                source_layer=(
                    system_layer.get(source_system)
                    if source_system is not None
                    else None
                ),
                target_system=target_system,
                target_layer=f"sideplane:{descriptor.sideplane_id}",
                required_module=hierarchy.application_composition_prefix,
            )
            continue

        source_facade_layer = facade_layer(source_module)
        source_composition_layer = composition_layer(source_module)
        target_facade_layer = facade_layer(target_module)
        target_facade_child_layer = facade_child_layer(target_module)

        if source_facade_layer is not None:
            layer = layers[source_facade_layer]
            if (
                layer.lower_layer_id is not None
                and target_module == layers[layer.lower_layer_id].facade_module
            ):
                continue
            if target_system in layer.members:
                required = root_prefixes[target_system] + ".api"
                if target_module == required:
                    continue
                add(
                    "layer_facade_internal_penetration",
                    edge,
                    source_layer=source_facade_layer,
                    target_system=target_system,
                    target_layer=system_layer.get(target_system),
                    required_module=required,
                )
                continue
            add(
                "layer_facade_illegal_dependency",
                edge,
                source_layer=source_facade_layer,
                target_system=target_system,
                target_layer=(
                    target_facade_layer
                    or target_facade_child_layer
                    or (system_layer.get(target_system) if target_system else None)
                ),
            )
            continue

        if source_composition_layer is not None:
            layer = layers[source_composition_layer]
            if (
                layer.lower_layer_id is not None
                and target_module == layers[layer.lower_layer_id].facade_module
            ):
                continue
            if target_system in layer.members:
                required = root_prefixes[target_system] + ".api"
                if target_module == required:
                    continue
                add(
                    "layer_composition_internal_penetration",
                    edge,
                    source_layer=source_composition_layer,
                    target_system=target_system,
                    target_layer=system_layer.get(target_system),
                    required_module=required,
                )
                continue
            add(
                "layer_composition_illegal_dependency",
                edge,
                source_layer=source_composition_layer,
                target_system=target_system,
                target_layer=(
                    target_facade_layer
                    or target_facade_child_layer
                    or (system_layer.get(target_system) if target_system else None)
                ),
            )
            continue

        if source_system is None:
            continue

        source_layer_id = system_layer[source_system]
        source_layer = layers[source_layer_id]
        lower_layer_id = source_layer.lower_layer_id
        required_lower = (
            None
            if lower_layer_id is None
            else layers[lower_layer_id].facade_module
        )

        if target_module == required_lower:
            continue

        if target_facade_child_layer is not None:
            add(
                "lower_layer_facade_internal_penetration",
                edge,
                source_system=source_system,
                source_layer=source_layer_id,
                target_layer=target_facade_child_layer,
                required_module=required_lower,
            )
            continue

        if target_facade_layer is not None:
            add(
                "non_adjacent_layer_facade_dependency",
                edge,
                source_system=source_system,
                source_layer=source_layer_id,
                target_layer=target_facade_layer,
                required_module=required_lower,
            )
            continue

        if target_system is None:
            continue

        target_layer_id = system_layer[target_system]
        if target_layer_id == source_layer_id:
            kind = "sibling_system_dependency"
        elif layer_order[target_layer_id] > layer_order[source_layer_id]:
            kind = "reverse_layer_dependency"
        elif lower_layer_id == target_layer_id:
            kind = "bypass_lower_layer_facade"
        else:
            kind = "skip_layer_dependency"

        add(
            kind,
            edge,
            source_system=source_system,
            source_layer=source_layer_id,
            target_system=target_system,
            target_layer=target_layer_id,
            required_module=required_lower,
        )

    return tuple(findings)


def audit_system_dependency_invariants(root: Path) -> list[SourceInvariantViolation]:
    root = Path(root).resolve()
    rows: list[SourceInvariantViolation] = []
    for finding in layer_dependency_findings(root):
        required = (
            ""
            if finding.required_module is None
            else f"; required facade={finding.required_module}"
        )
        rows.append(
            violation(
                root,
                root / finding.path,
                finding.kind,
                finding.line,
                f"{finding.source_module} -> {finding.target_module}{required}",
            )
        )
    return rows


__all__ = [
    "LayerDependencyFinding",
    "_declared_dependency_covers",
    "audit_system_dependency_invariants",
    "layer_dependency_findings",
]
