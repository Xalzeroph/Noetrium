"""Derived ownership matrix from the canonical system registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from noetrium_platform.foundation.kernel.kernel import (
    canonical_bytes,
    canonical_digest,
    strict_json_loads,
)


PLANES = frozenset({"foundation", "capabilities", "evidence", "research", "product"})


@dataclass(frozen=True, slots=True)
class OwnershipRow:
    system_id: str
    plane: str
    parent: str | None
    owner_kind: str
    state_authority: str
    journal_scope: str
    checkpoint_scope: str
    effect_policy: str
    replay_level: str
    public_abi: tuple[str, ...]
    audit_required: tuple[str, ...]
    row_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.system_id.strip() or not self.owner_kind.strip():
            raise ValueError("ownership row identity is required")
        if self.plane not in PLANES:
            raise ValueError(f"unknown ownership plane: {self.plane}")
        if not self.state_authority.strip():
            raise ValueError("ownership state_authority is required")
        object.__setattr__(self, "row_digest", canonical_digest({
            "system_id": self.system_id,
            "plane": self.plane,
            "parent": self.parent,
            "owner_kind": self.owner_kind,
            "state_authority": self.state_authority,
            "journal_scope": self.journal_scope,
            "checkpoint_scope": self.checkpoint_scope,
            "effect_policy": self.effect_policy,
            "replay_level": self.replay_level,
            "public_abi": self.public_abi,
            "audit_required": self.audit_required,
        }))

    def as_dict(self) -> dict[str, object]:
        return {
            "system_id": self.system_id,
            "plane": self.plane,
            "parent": self.parent,
            "owner_kind": self.owner_kind,
            "state_authority": self.state_authority,
            "journal_scope": self.journal_scope,
            "checkpoint_scope": self.checkpoint_scope,
            "effect_policy": self.effect_policy,
            "replay_level": self.replay_level,
            "public_abi": self.public_abi,
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

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "noetrium.ownership-matrix.v1",
            "source_digest": self.source_digest,
            "matrix_digest": self.matrix_digest,
            "rows": tuple(row.as_dict() for row in self.rows),
        }


def _plane(package_prefix: str) -> str:
    parts = package_prefix.split(".")
    return parts[1] if len(parts) > 1 and parts[1] in PLANES else "foundation"


def build_ownership_matrix(catalog: Mapping[str, object]) -> OwnershipMatrix:
    if not isinstance(catalog, Mapping) or not catalog:
        raise ValueError("system registry catalog must be a non-empty object")
    source_digest = canonical_digest(catalog)
    rows: list[OwnershipRow] = []
    for system_id in sorted(catalog):
        descriptor = catalog[system_id]
        if not isinstance(descriptor, Mapping):
            raise ValueError(f"catalog descriptor must be an object: {system_id}")
        missing = tuple(
            name for name in (
                "journal_scope", "checkpoint_scope", "effect_policy", "replay_level", "owner_kind"
            )
            if name not in descriptor
        )
        package_prefix = str(descriptor.get("package_prefix", ""))
        rows.append(OwnershipRow(
            system_id=system_id,
            plane=_plane(package_prefix),
            parent=descriptor.get("parent"),
            owner_kind=str(descriptor.get("owner_kind", "system-registry")),
            state_authority=str(descriptor.get("authority", "")),
            journal_scope=str(descriptor.get("journal_scope", "unclassified")),
            checkpoint_scope=str(descriptor.get("checkpoint_scope", "unclassified")),
            effect_policy=str(descriptor.get("effect_policy", "unclassified")),
            replay_level=str(descriptor.get("replay_level", "unclassified")),
            public_abi=tuple(str(item) for item in descriptor.get("shape", ())),
            audit_required=missing,
        ))
    return OwnershipMatrix(tuple(rows), source_digest)


def load_catalog(path: str | Path) -> dict[str, object]:
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
