from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.governance.system_registry.api import (
    audit_system_topology_source,
    system_catalog,
)

from .source_scan import SourceInvariantViolation, violation


def audit_system_topology_completeness(root: Path) -> list[SourceInvariantViolation]:
    """Project the canonical system-registry source audit into architecture violations.

    Discovery and shape rules live only in system_registry.api.topology. Architecture
    consumes that evidence instead of maintaining a second filesystem classifier.
    """

    root = Path(root).resolve()
    descriptors = tuple(system_catalog())
    audit = audit_system_topology_source(root, descriptors=descriptors)
    rows: list[SourceInvariantViolation] = []
    canonical_catalog = root / "noetrium_platform/foundation/governance/system_registry/catalog.json"
    source = canonical_catalog if canonical_catalog.is_file() else Path(__file__)

    for package in audit.stale_registered_packages:
        descriptor = next(row for row in descriptors if row.package_prefix == package)
        rows.append(violation(
            root, source, "stale_catalog_package", 1,
            f"catalog descriptor {descriptor.identity.key} declares package {package} but that Python package is absent",
        ))
    for detail in audit.incomplete_registered_packages:
        package = detail.split(" (missing:", 1)[0]
        descriptor = next(row for row in descriptors if row.package_prefix == package)
        rows.append(violation(
            root, source, "incomplete_catalog_package_shape", 1,
            f"catalog descriptor {descriptor.identity.key} declares standard shape but source is {detail}",
        ))
    for module in audit.unregistered_standard_packages:
        package = root.joinpath(*module.split("."))
        marker = package / "__init__.py"
        rows.append(violation(
            root, marker if marker.is_file() else source, "unregistered_standard_system", 1,
            f"system-shaped source exists at {module} but no canonical system_registry/catalog.json descriptor owns it",
        ))
    return rows


__all__ = ["audit_system_topology_completeness"]
