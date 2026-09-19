from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from noetrium_platform.foundation.kernel.kernel import (
    JsonDocument,
    JsonInput,
    canonical_bytes,
    canonical_digest,
    strict_json_loads,
)


PLANES = frozenset({"foundation", "capabilities", "evidence", "research", "product"})
NODE_KINDS = frozenset({
    "authority", "facet", "projection", "provider", "adapter", "policy",
    "tool", "product_surface", "reference",
})

@dataclass(frozen=True, slots=True)
class OwnershipRow:
    system_id: str
    plane: str
    parent: str | None
    node_kind: str
    canonical_authority: str | None
    state_authority: str
    downstream_surface: str
    public_abi: tuple[str, ...]
    requires: tuple[str, ...]
    provides: tuple[str, ...]
    audit_required: tuple[str, ...]
    row_digest: str = field(init=False)

    @property
    def direct_authority(self) -> bool:
        return self.node_kind == "authority"

    def __post_init__(self) -> None:
        if not self.system_id.strip():
            raise ValueError("ownership row system_id is required")
        if self.plane not in PLANES:
            raise ValueError(f"unknown ownership plane: {self.plane}")
        if self.node_kind not in NODE_KINDS:
            raise ValueError(f"unknown ownership node kind: {self.node_kind}")
        if self.direct_authority and self.canonical_authority != self.system_id:
            raise ValueError("direct authority must canonically own itself")
        if not self.direct_authority and self.canonical_authority == self.system_id:
            raise ValueError("non-authority node cannot canonically own itself")
        if not self.state_authority.strip():
            raise ValueError("ownership state_authority is required")
        if not self.downstream_surface.strip():
            raise ValueError("ownership downstream_surface is required")
        object.__setattr__(self, "row_digest", canonical_digest({
            "system_id": self.system_id,
            "plane": self.plane,
            "parent": self.parent,
            "node_kind": self.node_kind,
            "canonical_authority": self.canonical_authority,
            "state_authority": self.state_authority,
            "downstream_surface": self.downstream_surface,
            "public_abi": self.public_abi,
            "requires": self.requires,
            "provides": self.provides,
            "audit_required": self.audit_required,
        }))

    def as_dict(self) -> dict[str, JsonInput]:
        return {
            "system_id": self.system_id,
            "plane": self.plane,
            "parent": self.parent,
            "node_kind": self.node_kind,
            "canonical_authority": self.canonical_authority,
            "direct_authority": self.direct_authority,
            "state_authority": self.state_authority,
            "downstream_surface": self.downstream_surface,
            "public_abi": self.public_abi,
            "requires": self.requires,
            "provides": self.provides,
            "audit_required": self.audit_required,
            "row_digest": self.row_digest,
        }


@dataclass(frozen=True, slots=True)
class OwnershipMatrix:
    rows: tuple[OwnershipRow, ...]
    source_digest: str
    matrix_digest: str = field(init=False)

    def __post_init__(self) -> None:
        ids = tuple(row.system_id for row in self.rows)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("ownership rows must be sorted and unique")
        object.__setattr__(
            self,
            "matrix_digest",
            canonical_digest({
                "source_digest": self.source_digest,
                "rows": tuple(row.as_dict() for row in self.rows),
            }),
        )
    def as_dict(self) -> dict[str, JsonInput]:
        return {
            "schema": "noetrium.ownership-matrix.v2",
            "source_digest": self.source_digest,
            "matrix_digest": self.matrix_digest,
            "rows": tuple(row.as_dict() for row in self.rows),
        }


def _plane(package_prefix: str) -> str:
    parts = package_prefix.split(".")
    return parts[1] if len(parts) > 1 and parts[1] in PLANES else "foundation"


def _string_tuple(value: object, field: str, system_id: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"catalog {field} must be a string list: {system_id}")
    result = tuple(value)
    if len(result) != len(set(result)):
        raise ValueError(f"catalog {field} must be unique: {system_id}")
    return result


def build_ownership_matrix(catalog: JsonDocument) -> OwnershipMatrix:
    if not isinstance(catalog, Mapping) or not catalog:
        raise ValueError("system registry catalog must be a non-empty object")
    source_digest = canonical_digest(catalog)
    direct_authorities = {
        system_id for system_id, descriptor in catalog.items()
        if isinstance(descriptor, Mapping) and descriptor.get("node_kind") == "authority"
    }
    rows: list[OwnershipRow] = []
    for system_id in sorted(catalog):
        descriptor = catalog[system_id]
        if not isinstance(descriptor, Mapping):
            raise ValueError(f"catalog descriptor must be an object: {system_id}")
        required = (
            "authority", "package_prefix", "parent", "shape", "requires", "provides",
            "node_kind", "canonical_authority", "downstream_surface",
        )
        missing = tuple(name for name in required if name not in descriptor)
        if missing:
            raise ValueError(f"catalog ownership metadata missing for {system_id}: {missing}")
        node_kind = str(descriptor["node_kind"])
        if node_kind not in NODE_KINDS:
            raise ValueError(f"catalog node kind is invalid for {system_id}: {node_kind}")
        canonical_value = descriptor["canonical_authority"]
        canonical = None if canonical_value is None else str(canonical_value)
        if node_kind == "authority":
            if canonical != system_id:
                raise ValueError(f"authority node must canonically own itself: {system_id}")
        elif canonical is not None and canonical not in direct_authorities:
            raise ValueError(f"canonical authority is not direct for {system_id}: {canonical}")
        canonical_descriptor = catalog.get(canonical) if canonical is not None else None
        if canonical_descriptor is not None and not isinstance(canonical_descriptor, Mapping):
            raise ValueError(f"canonical authority descriptor is invalid: {canonical}")
        state_authority = str(
            descriptor["authority"]
            if node_kind == "authority"
            else canonical_descriptor["authority"] if canonical_descriptor is not None else "none"
        )
        package_prefix = str(descriptor["package_prefix"])
        parent_value = descriptor["parent"]
        parent = None if parent_value is None else str(parent_value).replace(".", "/")
        rows.append(OwnershipRow(
            system_id=system_id,
            plane=_plane(package_prefix),
            parent=parent,
            node_kind=node_kind,
            canonical_authority=canonical,
            state_authority=state_authority,
            downstream_surface=str(descriptor["downstream_surface"]),
            public_abi=_string_tuple(descriptor["shape"], "shape", system_id),
            requires=_string_tuple(descriptor["requires"], "requires", system_id),
            provides=_string_tuple(descriptor["provides"], "provides", system_id),
            audit_required=(),
        ))
    return OwnershipMatrix(tuple(rows), source_digest)


def load_catalog(path: str | Path) -> dict[str, JsonInput]:
    value = strict_json_loads(Path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError("system registry catalog must be an object")
    return value


def write_matrix(matrix: OwnershipMatrix, path: str | Path) -> None:
    Path(path).write_bytes(canonical_bytes(matrix.as_dict(), indent=2))


__all__ = [
    "OwnershipMatrix",
    "OwnershipRow",
    "build_ownership_matrix",
    "load_catalog",
    "write_matrix",
]
