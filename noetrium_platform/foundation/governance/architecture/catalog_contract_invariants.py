from __future__ import annotations

import ast
import json
from pathlib import Path

from noetrium_platform.foundation.governance.system_registry.api import system_catalog

from .source_index import source_text, source_tree
from .source_scan import SourceInvariantViolation, violation


_CONTRACT_FIELDS = (
    "system_id",
    "node",
    "package_prefix",
    "authority_id",
    "owns",
    "must_not_own",
    "api_module",
    "runtime_module",
    "provider_module",
    "composition_module",
)


def _system_leaf_contract(tree: ast.AST) -> tuple[int, dict[str, str]] | None:
    """Return one literal SystemLeafContract declaration from an API boundary."""

    for item in ast.walk(tree):
        if not isinstance(item, ast.Call):
            continue
        fn = item.func
        if not (isinstance(fn, ast.Name) and fn.id == "SystemLeafContract"):
            continue
        values: dict[str, str] = {}
        by_name = {keyword.arg: keyword.value for keyword in item.keywords if keyword.arg}
        for field in _CONTRACT_FIELDS:
            raw = by_name.get(field)
            if not isinstance(raw, ast.Constant) or not isinstance(raw.value, str):
                continue
            values[field] = raw.value
        return item.lineno, values
    return None


def _catalog_path(root: Path) -> Path:
    return root / "noetrium_platform/foundation/governance/system_registry/catalog.json"


def _legacy_authority_metadata(root: Path) -> dict[str, str]:
    """Read historical authority labels from the exact frozen catalog source.

    After authority consolidation, non-authority nodes can retain the old
    ``authority`` string only as migration/declaration metadata.  The typed
    runtime descriptor intentionally drops that label from ``authorities``.
    Leaf-contract consistency therefore compares declaration metadata with the
    raw catalog while direct write authority remains governed solely by
    ``SystemDescriptor.node_kind`` and ``SystemDescriptor.authorities``.
    """

    document = json.loads(source_text(_catalog_path(root)))
    if not isinstance(document, dict) or not document:
        raise RuntimeError("canonical system catalog must be a non-empty object")
    result: dict[str, str] = {}
    for key, raw in document.items():
        if not isinstance(key, str) or not isinstance(raw, dict):
            raise RuntimeError("canonical system catalog entries must be objects")
        authority = raw.get("authority")
        if not isinstance(authority, str):
            raise RuntimeError(f"catalog authority metadata must be text for {key!r}")
        result[key] = authority
    return result


def _expected_contract(descriptor, *, legacy_authority_id: str) -> dict[str, str]:
    package = descriptor.package_prefix
    return {
        "system_id": descriptor.identity.system_id,
        "node": descriptor.identity.key,
        "package_prefix": package,
        "authority_id": legacy_authority_id,
        "owns": descriptor.owns,
        "must_not_own": descriptor.must_not_own,
        "api_module": package + ".api",
        "runtime_module": package + ".runtime",
        "provider_module": package + ".providers",
        "composition_module": package + ".composition",
    }


def audit_catalog_contract_consistency(root: Path) -> list[SourceInvariantViolation]:
    """Bind declared leaf contracts to the canonical registry without importing them.

    A synthetic source tree used to exercise an unrelated source invariant may
    intentionally omit the canonical registry.  In that case this *specific*
    catalog/leaf consistency invariant is not applicable and returns no rows;
    the caller still runs every other source invariant against the synthetic
    tree.  If a registry file is present, parsing and semantic drift remain
    fail-closed.

    Algorithm-Complexity: O(N)
    Algorithm-Rationale: N is the number of registered descriptors plus AST nodes in
    API boundaries that already declare SystemLeafContract; every descriptor and AST
    is visited at most once and comparisons are over a fixed field set.
    """

    root = Path(root).resolve()
    if not _catalog_path(root).is_file():
        return []

    rows: list[SourceInvariantViolation] = []
    legacy_authority = _legacy_authority_metadata(root)
    for descriptor in system_catalog():
        boundary = root.joinpath(*descriptor.package_prefix.split("."), "api", "boundary.py")
        if not boundary.is_file():
            continue
        declared = _system_leaf_contract(source_tree(boundary))
        if declared is None:
            continue
        line, actual = declared
        try:
            authority_id = legacy_authority[descriptor.identity.key]
        except KeyError as exc:
            raise RuntimeError(
                f"runtime descriptor {descriptor.identity.key!r} is absent from canonical catalog"
            ) from exc
        expected = _expected_contract(
            descriptor,
            legacy_authority_id=authority_id,
        )
        missing = tuple(field for field in _CONTRACT_FIELDS if field not in actual)
        if missing:
            rows.append(violation(
                root,
                boundary,
                "leaf_contract_metadata_nonliteral",
                line,
                "SystemLeafContract metadata must be literal for registry verification: "
                + ", ".join(missing),
            ))
            continue
        for field in _CONTRACT_FIELDS:
            if actual[field] == expected[field]:
                continue
            rows.append(violation(
                root,
                boundary,
                "leaf_contract_catalog_drift",
                line,
                (
                    f"{descriptor.identity.key} {field} drift: catalog={expected[field]!r} "
                    f"leaf_contract={actual[field]!r}"
                ),
            ))
    return rows


__all__ = ["audit_catalog_contract_consistency"]
