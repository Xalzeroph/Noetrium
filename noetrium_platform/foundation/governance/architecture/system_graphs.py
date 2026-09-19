from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.governance.system_registry.api import system_catalog


@dataclass(frozen=True, slots=True)
class SystemGraphEdge:
    source: str
    target: str
    relation: str = "requires"


@dataclass(frozen=True, slots=True)
class SubsystemGraphEdge:
    source: str
    target: str
    relation: str
    package_prefix: str
    provides: tuple[str, ...]
    requires: tuple[str, ...]
    authorities: tuple[str, ...]
    components: tuple[str, ...]


def declared_system_graph() -> tuple[SystemGraphEdge, ...]:
    rows: list[SystemGraphEdge] = []
    for descriptor in system_catalog():
        if not descriptor.identity.is_system:
            continue
        for target in descriptor.requires:
            rows.append(SystemGraphEdge(descriptor.identity.system_id, target))
    return tuple(sorted(rows, key=lambda row: (row.source, row.target)))


def declared_subsystem_graph() -> tuple[SubsystemGraphEdge, ...]:
    rows: list[SubsystemGraphEdge] = []
    for descriptor in system_catalog():
        if descriptor.identity.is_system:
            continue
        parent = descriptor.parent_key
        if parent is None:
            raise RuntimeError(f"subsystem has no parent: {descriptor.identity.key}")
        rows.append(SubsystemGraphEdge(
            source=parent,
            target=descriptor.identity.key,
            relation="contains",
            package_prefix=descriptor.package_prefix,
            provides=descriptor.provides,
            requires=descriptor.requires,
            authorities=tuple(authority.authority_id for authority in descriptor.authorities),
            components=descriptor.components,
        ))
    return tuple(sorted(rows, key=lambda row: row.target))


__all__ = [
    "SubsystemGraphEdge",
    "SystemGraphEdge",
    "declared_subsystem_graph",
    "declared_system_graph",
]
