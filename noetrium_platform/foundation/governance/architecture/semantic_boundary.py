from __future__ import annotations

import json
from pathlib import Path

from .api.semantic_boundary import (
    SemanticBoundaryClassification,
    SemanticBoundaryEvidence,
)

_TEMPLATE_FILES = frozenset({"boundary.py", "owner.py", "default.py"})
_GENERIC_MARKERS = (
    "BoundSystemLeafRuntime",
    "FileLeafStateStore",
    "LeafHandler",
    "SystemLeafProvider",
    "SystemLeafRuntimeOwner",
)
_PLANES = ("api", "runtime", "providers", "composition")


def _string_tuple(value: object, *, node: str, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"invalid semantic-boundary catalog {field} for {node!r}")
    result = tuple(value)
    if len(result) != len(set(result)):
        raise ValueError(f"duplicate semantic-boundary catalog {field} for {node!r}")
    return result


def _catalog(root: Path) -> dict[str, object]:
    path = root / "noetrium_platform/foundation/governance/system_registry/catalog.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not document:
        raise ValueError("semantic-boundary catalog must be a non-empty object")
    return document


def _generic_leaf_flags(text: str) -> tuple[bool, bool]:
    generic_leaf_runtime = any(marker in text for marker in _GENERIC_MARKERS)
    generic_state_capable = generic_leaf_runtime and (
        "state_path" in text or "FileLeafStateStore" in text
    )
    return generic_leaf_runtime, generic_state_capable


def _scan_semantic_source(base: Path) -> tuple[tuple[str, ...], bool, bool]:
    """Scan disjoint plane files once for semantic and generic-leaf evidence."""
    semantic_files: list[str] = []
    generic_leaf_runtime = False
    generic_state_capable = False
    for plane in _PLANES:
        plane_root = base / plane
        if not plane_root.is_dir():
            continue
        for source in sorted(plane_root.glob("*.py"), key=lambda item: item.name):
            if source.name == "__init__.py":
                continue
            text = source.read_text(encoding="utf-8-sig")
            file_generic, file_state = _generic_leaf_flags(text)
            generic_leaf_runtime |= file_generic
            generic_state_capable |= file_state
            if source.name not in _TEMPLATE_FILES:
                semantic_files.append(source.relative_to(base).as_posix())
    return tuple(sorted(semantic_files)), generic_leaf_runtime, generic_state_capable


def classify_semantic_boundaries(root: Path) -> tuple[SemanticBoundaryEvidence, ...]:
    root = Path(root).resolve()
    rows: list[SemanticBoundaryEvidence] = []
    for node, raw in sorted(_catalog(root).items()):
        if not isinstance(node, str) or not isinstance(raw, dict):
            raise ValueError("semantic-boundary catalog entries must be typed objects")
        package_prefix = raw.get("package_prefix")
        if not isinstance(package_prefix, str) or not package_prefix.startswith("noetrium_platform."):
            raise ValueError(f"invalid semantic-boundary package prefix for {node!r}")
        requires = _string_tuple(raw.get("requires"), node=node, field="requires")
        provides = _string_tuple(raw.get("provides"), node=node, field="provides")
        components = _string_tuple(raw.get("components"), node=node, field="components")
        base = root.joinpath(*package_prefix.split("."))
        semantic_files, generic_leaf_runtime, generic_state_capable = _scan_semantic_source(base)
        if semantic_files:
            classification = SemanticBoundaryClassification.IMPLEMENTED_SEMANTIC_BOUNDARY
        elif requires or provides or components:
            classification = SemanticBoundaryClassification.DECLARATIVE_ONLY
        else:
            classification = SemanticBoundaryClassification.DELETE_CANDIDATE
        rows.append(SemanticBoundaryEvidence(
            node=node,
            package_prefix=package_prefix,
            classification=classification,
            generic_leaf_runtime=generic_leaf_runtime,
            generic_state_capable=generic_state_capable,
            semantic_source_files=tuple(sorted(semantic_files)),
            requires=requires,
            provides=provides,
            components=components,
        ))
    return tuple(rows)


def classify_semantic_boundary(root: Path, node: str) -> SemanticBoundaryEvidence:
    for row in classify_semantic_boundaries(root):
        if row.node == node:
            return row
    raise KeyError(f"semantic boundary is not registered: {node}")


__all__ = ["classify_semantic_boundaries", "classify_semantic_boundary"]
