from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.governance.system_registry.api import (
    SystemDescriptor,
    system_catalog,
)

from .import_graph import scan_imports
from .planes import is_composition_module
from .source_scan import SourceInvariantViolation, violation


# Leaf contracts are declarative boundary metadata used by every subsystem.
# Keep this exemption exact: exempting the whole platform kernel would hide
# ordinary cross-system runtime dependencies.
FOUNDATIONAL_MODULE_PREFIXES = (
    "noetrium_platform.foundation.kernel.kernel.leaf_contract",
)


def _owner_for_module(
    descriptors: tuple[SystemDescriptor, ...],
    module: str,
) -> SystemDescriptor | None:
    candidates = tuple(
        row
        for row in descriptors
        if module == row.package_prefix or module.startswith(row.package_prefix + ".")
    )
    return max(candidates, key=lambda row: len(row.package_prefix)) if candidates else None


def _declared_system_cycles(descriptors: tuple[SystemDescriptor, ...]) -> tuple[tuple[str, ...], ...]:
    """Return strongly-connected components in the declared top-level dependency graph."""

    graph = {
        row.identity.system_id: tuple(row.requires)
        for row in descriptors
        if row.identity.is_system
    }
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph.get(node, ()):
            if target not in graph:
                continue
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while True:
            item = stack.pop()
            on_stack.remove(item)
            component.append(item)
            if item == node:
                break
        if len(component) > 1:
            components.append(tuple(sorted(component)))
        elif node in graph.get(node, ()):
            components.append((node,))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return tuple(sorted(components))


def _declared_dependency_covers(dependency: str, target_key: str) -> bool:
    """Return whether a declared system/subsystem dependency covers the target owner."""

    return target_key == dependency or target_key.startswith(dependency + "/")


def audit_system_dependency_invariants(root: Path) -> list[SourceInvariantViolation]:
    """Enforce explicit cross-system dependencies and an acyclic system dependency DAG.

    Containment and dependency are deliberately separate concepts. A subsystem may
    declare dependencies specific to its wiring role (for example Platform
    Composition) without forcing those dependencies onto its parent system.
    """

    root = Path(root).resolve()
    descriptors = system_catalog()
    top_level = {
        row.identity.system_id: row
        for row in descriptors
        if row.identity.is_system
    }
    rows: list[SourceInvariantViolation] = []

    catalog_path = root / "noetrium_platform/foundation/governance/system_registry/api/topology.py"
    for component in _declared_system_cycles(descriptors):
        rows.append(violation(
            root,
            catalog_path,
            "system_dependency_cycle",
            1,
            "declared top-level system dependency cycle: " + " -> ".join(component),
        ))

    seen: set[tuple[str, str, str, int]] = set()
    for edge in scan_imports(root, package_roots=("noetrium_platform",)):
        if is_composition_module(edge.source_module):
            continue
        if any(
            edge.target_module == prefix
            or edge.target_module.startswith(prefix + ".")
            for prefix in FOUNDATIONAL_MODULE_PREFIXES
        ):
            continue
        source = _owner_for_module(descriptors, edge.source_module)
        target = _owner_for_module(descriptors, edge.target_module)
        if source is None or target is None:
            continue
        source_system = source.identity.system_id
        target_system = target.identity.system_id
        if source_system == target_system:
            continue
        target_key = target.identity.key
        declared = (*top_level[source_system].requires, *source.requires)
        if any(_declared_dependency_covers(item, target_key) for item in declared):
            continue
        key = (source_system, target_system, edge.path, edge.line)
        if key in seen:
            continue
        seen.add(key)
        rows.append(violation(
            root,
            root / edge.path,
            "system_dependency_declaration",
            edge.line,
            f"{source.identity.key} depends on {target_system} but the dependency is not declared for the subsystem or its parent system",
        ))
    return rows


__all__ = ["audit_system_dependency_invariants"]
