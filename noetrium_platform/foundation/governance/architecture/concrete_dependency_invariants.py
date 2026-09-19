from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.governance.system_registry.api import SystemDescriptor, system_catalog

from .import_graph import scan_imports
from .planes import is_composition_module
from .source_scan import SourceInvariantViolation, violation


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


def _is_concrete_target(owner: SystemDescriptor, module: str) -> bool:
    remainder = module[len(owner.package_prefix):].lstrip(".")
    return (
        remainder == "runtime"
        or remainder.startswith("runtime.")
        or remainder == "providers"
        or remainder.startswith("providers.")
    )


def _shares_canonical_authority(source: SystemDescriptor, target: SystemDescriptor) -> bool:
    """Return whether two topology nodes are facets of the same truth authority.

    Package/subsystem identity is not an authority boundary.  The consolidation
    spec permits multiple facets/providers to cooperate inside one canonical
    authority implementation.  Explicit ``None`` never creates an equivalence
    class: outside-authority-graph nodes must not gain mutual concrete access
    merely because both lack a truth owner.
    """

    source_key = source.canonical_authority_key
    target_key = target.canonical_authority_key
    return source_key is not None and source_key == target_key


def audit_cross_subsystem_concrete_dependencies(root: Path) -> list[SourceInvariantViolation]:
    """Forbid bypassing another canonical authority's contract boundary.

    Composition roots may bind concrete implementations.  Runtime/domain code may
    also cooperate with concrete facets that belong to its *same* canonical
    authority.  Crossing to another authority's runtime/provider implementation
    requires that authority's API contract and composition-time injection.
    """

    root = Path(root).resolve()
    descriptors = system_catalog()
    rows: list[SourceInvariantViolation] = []
    for edge in scan_imports(root, package_roots=("noetrium_platform",)):
        if is_composition_module(edge.source_module):
            continue
        source = _owner_for_module(descriptors, edge.source_module)
        target = _owner_for_module(descriptors, edge.target_module)
        if source is None or target is None or source.identity.key == target.identity.key:
            continue
        if _shares_canonical_authority(source, target):
            continue
        if not _is_concrete_target(target, edge.target_module):
            continue
        rows.append(violation(
            root,
            root / edge.path,
            "cross_subsystem_concrete_dependency",
            edge.line,
            (
                f"{source.identity.key} imports concrete implementation "
                f"{edge.target_module} from {target.identity.key}; depend on its API contract "
                "and inject the implementation from composition"
            ),
        ))
    return rows


__all__ = ["audit_cross_subsystem_concrete_dependencies"]
