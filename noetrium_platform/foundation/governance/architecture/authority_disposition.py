from __future__ import annotations

"""Normative authority-topology classification and migration-matrix validation.

This module is the executable counterpart of
``NOETRIUM_AUTHORITY_CONSOLIDATION_EXECUTION_SPEC_20260916.md``.  The vocabulary
is intentionally closed: source layout may grow, but authority semantics may
not acquire ad-hoc node kinds or migration states.
"""

from dataclasses import dataclass
from typing import Mapping, Sequence

from noetrium_platform.foundation.kernel.kernel import JsonDocument


NODE_KINDS = frozenset(
    {
        "authority",
        "facet",
        "projection",
        "provider",
        "adapter",
        "policy",
        "tool",
        "product_surface",
    }
)

DISPOSITIONS = frozenset(
    {
        "KEEP",
        "CONSOLIDATE",
        "FACET",
        "PROJECTION",
        "PROVIDER",
        "ADAPTER",
        "POLICY",
        "TOOL",
        "PRODUCT_SURFACE",
        "REMOVE",
    }
)

EXTERNAL_NON_AUTHORITATIVE = "external/non_authoritative"
OUTSIDE_RUNTIME_AUTHORITY_GRAPH = "outside_runtime_authority_graph"

_KIND_DISPOSITION = {
    "authority": "KEEP",
    "facet": "CONSOLIDATE",
    "projection": "PROJECTION",
    "provider": "PROVIDER",
    "adapter": "ADAPTER",
    "policy": "POLICY",
    "tool": "TOOL",
    "product_surface": "PRODUCT_SURFACE",
}


@dataclass(frozen=True, slots=True)
class AuthorityDispositionRow:
    path: str
    current_authority: str
    node_kind: str
    disposition: str
    canonical_authority: str | None
    reason: str
    migration_target: str
    downstream_surface: str

    def as_dict(self) -> dict[str, str | None]:
        return {
            "path": self.path,
            "current_authority": self.current_authority,
            "node_kind": self.node_kind,
            "disposition": self.disposition,
            "canonical_authority": self.canonical_authority,
            "reason": self.reason,
            "migration_target": self.migration_target,
            "downstream_surface": self.downstream_surface,
        }


def _text(value: object, *, field: str, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"authority disposition {field} is required for {path!r}")
    return value.strip()


def _optional_text(value: object, *, field: str | None = None, path: str = "<unknown>") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        name = field or "value"
        raise ValueError(f"authority disposition {name} must be null or non-empty text for {path!r}")
    return value.strip()


def canonical_target(path: str, descriptor: JsonDocument) -> str | None:
    """Return the accepted truth authority declared for one topology node.

    The canonical registry is authoritative: this function never infers a truth
    owner from path names, ancestry, or historical authority labels.  Explicit
    ``canonical_authority=null`` means the node is deliberately outside the
    runtime truth-authority graph when its node kind permits that semantics.
    """

    kind = _text(descriptor.get("node_kind"), field="node_kind", path=path)
    if kind not in NODE_KINDS:
        raise ValueError(f"unsupported authority node kind for {path!r}: {kind!r}")
    if "canonical_authority" not in descriptor:
        raise ValueError(f"authority disposition canonical_authority is required for {path!r}")

    declared = _optional_text(
        descriptor.get("canonical_authority"),
        field="canonical_authority",
        path=path,
    )
    if kind == "authority":
        if declared != path:
            raise ValueError(f"authority {path!r} must canonically own itself")
        return path
    if declared is not None:
        if declared == path:
            raise ValueError(f"non-authority {path!r} cannot canonically own itself")
        return declared

    # Policy and projection surfaces can intentionally aggregate or evaluate
    # multiple authorities without becoming a new truth owner.  Their explicit
    # null target therefore means outside-runtime-authority-graph.
    if kind in {"policy", "projection"}:
        return None
    if kind in {"provider", "adapter", "tool", "product_surface"}:
        return EXTERNAL_NON_AUTHORITATIVE

    parent = descriptor.get("parent")
    if parent is None and kind == "facet":
        return None

    raise ValueError(
        f"non-authority {path!r} must identify the authority it depends on or projects from"
    )


def build_authority_disposition_matrix(
    catalog: JsonDocument,
) -> tuple[AuthorityDispositionRow, ...]:
    if not catalog:
        raise ValueError("authority disposition catalog must be non-empty")

    authority_paths = {
        path
        for path, raw in catalog.items()
        if isinstance(raw, Mapping) and raw.get("node_kind") == "authority"
    }
    rows: list[AuthorityDispositionRow] = []
    for path, raw in catalog.items():
        if not isinstance(path, str) or not path.strip() or not isinstance(raw, dict):
            raise ValueError("authority disposition catalog entries must be typed objects")
        kind = _text(raw.get("node_kind"), field="node_kind", path=path)
        if kind not in NODE_KINDS:
            raise ValueError(f"unsupported authority node kind for {path!r}: {kind!r}")
        target = canonical_target(path, raw)
        if target not in {None, EXTERNAL_NON_AUTHORITATIVE} and target not in authority_paths:
            raise ValueError(
                f"canonical authority target {target!r} for {path!r} is not a direct authority"
            )

        legacy_authority = _optional_text(raw.get("authority"), field="authority", path=path)
        if kind == "authority":
            current_authority = _text(
                legacy_authority,
                field="authority",
                path=path,
            )
        else:
            # Non-authority nodes may retain the historical authority label only
            # as migration metadata. Runtime topology materialization must not
            # turn this field into AuthorityDescriptor/write ownership.
            current_authority = legacy_authority or target or EXTERNAL_NON_AUTHORITATIVE

        migration_target = (
            OUTSIDE_RUNTIME_AUTHORITY_GRAPH
            if target in {None, EXTERNAL_NON_AUTHORITATIVE}
            else target
        )
        rows.append(
            AuthorityDispositionRow(
                path=path,
                current_authority=current_authority,
                node_kind=kind,
                disposition=_KIND_DISPOSITION[kind],
                canonical_authority=target,
                reason=_text(raw.get("owns"), field="owns", path=path),
                migration_target=migration_target,
                downstream_surface=_text(
                    raw.get("downstream_surface", "public"),
                    field="downstream_surface",
                    path=path,
                ),
            )
        )
    return tuple(rows)


def validate_authority_disposition_matrix(
    rows: Sequence[JsonDocument],
    catalog: JsonDocument,
) -> tuple[AuthorityDispositionRow, ...]:
    expected = build_authority_disposition_matrix(catalog)
    expected_by_path = {row.path: row for row in expected}
    seen: set[str] = set()
    parsed: list[AuthorityDispositionRow] = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("authority disposition rows must be objects")
        path = _text(raw.get("path"), field="path", path="<unknown>")
        if path in seen:
            raise ValueError(f"duplicate authority disposition path: {path!r}")
        seen.add(path)
        row = AuthorityDispositionRow(
            path=path,
            current_authority=_text(raw.get("current_authority"), field="current_authority", path=path),
            node_kind=_text(raw.get("node_kind"), field="node_kind", path=path),
            disposition=_text(raw.get("disposition"), field="disposition", path=path),
            canonical_authority=_optional_text(
                raw.get("canonical_authority"),
                field="canonical_authority",
                path=path,
            ),
            reason=_text(raw.get("reason"), field="reason", path=path),
            migration_target=_text(raw.get("migration_target"), field="migration_target", path=path),
            downstream_surface=_text(raw.get("downstream_surface", "public"), field="downstream_surface", path=path),
        )
        if row.node_kind not in NODE_KINDS:
            raise ValueError(f"unsupported authority node kind for {path!r}: {row.node_kind!r}")
        if row.disposition not in DISPOSITIONS:
            raise ValueError(f"unsupported authority disposition for {path!r}: {row.disposition!r}")
        expected_row = expected_by_path.get(path)
        if expected_row is None:
            raise ValueError(f"authority disposition row is not in the live catalog: {path!r}")
        if row != expected_row:
            raise ValueError(
                f"authority disposition row drift for {path!r}: "
                f"expected {expected_row.as_dict()!r}, got {row.as_dict()!r}"
            )
        parsed.append(row)

    missing = tuple(path for path in expected_by_path if path not in seen)
    if missing:
        raise ValueError(f"authority disposition matrix is missing catalog nodes: {missing!r}")
    return tuple(parsed)


__all__ = [
    "AuthorityDispositionRow",
    "DISPOSITIONS",
    "EXTERNAL_NON_AUTHORITATIVE",
    "NODE_KINDS",
    "OUTSIDE_RUNTIME_AUTHORITY_GRAPH",
    "build_authority_disposition_matrix",
    "canonical_target",
    "validate_authority_disposition_matrix",
]
