from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, imports, violation


def _audit_error_api_firewall(root: Path) -> list[SourceInvariantViolation]:
    api = root / "noetrium_platform" / "foundation" / "kernel" / "kernel" / "errors"
    if not api.exists():
        return []
    forbidden = (
        "noetrium_platform.capabilities.participant",
        "noetrium_platform.research.experimentation",
        "noetrium_platform.research.execution",
        "noetrium_platform.capabilities.model",
        "noetrium_platform.infrastructure.lifecycle",
        "noetrium_platform.infrastructure.reliability",
        "noetrium_platform.evidence.observability",
        "noetrium_platform.foundation.governance",
        "noetrium_platform.product.operator",
        "noetrium_platform.composition",
    )
    rows: list[SourceInvariantViolation] = []
    for path in sorted(api.rglob("*.py")):
        for module, line in imports(path):
            if module.startswith(forbidden):
                rows.append(violation(
                    root,
                    path,
                    "error_api_dependency_firewall",
                    line,
                    f"kernel error authority imports higher-layer subsystem {module}",
                ))
    return rows


def _raw_exception_renderings(path: Path) -> tuple[tuple[int, str], ...]:
    """Find direct rendering of exception objects in diagnostic-facing layers.

    Persisted/user-visible exception text must go through
    ``error_api.describe_exception``.  Handler-bound exception names are always
    tracked; the conventional ``exc`` parameter is tracked as well so helper
    functions cannot bypass the policy by receiving an exception from callers.
    """

    tree = source_tree(path)
    exception_names = {"exc"}
    exception_names.update(
        handler.name
        for handler in ast.walk(tree)
        if isinstance(handler, ast.ExceptHandler) and isinstance(handler.name, str)
    )
    rows: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"str", "repr"}
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in exception_names
        ):
            rows.add((node.lineno, f"{node.func.id}({node.args[0].id})"))
        elif (
            isinstance(node, ast.FormattedValue)
            and isinstance(node.value, ast.Name)
            and node.value.id in exception_names
        ):
            rows.add((node.lineno, f"formatted exception {{{node.value.id}}}"))
    return tuple(sorted(rows))


def _audit_error_semantic_authority(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    for legacy in (
        root / "noetrium_platform" / "failure_api" / "redaction.py",
        root / "noetrium_platform" / "infrastructure" / "reliability" / "forensics" / "redaction.py",
    ):
        if legacy.exists():
            rows.append(violation(
                root,
                legacy,
                "error_semantic_authority",
                1,
                "redaction/error normalization must remain in noetrium_platform.foundation.kernel.kernel.errors",
            ))

    critical = (
        root / "noetrium_platform" / "foundation" / "kernel" / "kernel",
        root / "noetrium_platform" / "evidence" / "observability",
        root / "noetrium_platform" / "infrastructure" / "reliability" / "forensics",
        root / "noetrium_platform" / "product" / "operator",
        root / "noetrium_platform" / "infrastructure" / "reliability" / "diagnostics",
    )
    for base in critical:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if (root / "noetrium_platform" / "foundation" / "kernel" / "kernel" / "errors") in path.parents:
                continue
            for line, rendering in _raw_exception_renderings(path):
                rows.append(violation(
                    root,
                    path,
                    "error_semantic_authority",
                    line,
                    f"raw exception text is surfaced directly ({rendering}); use error_api.describe_exception",
                ))
    return rows


def audit_error_invariants(root: Path) -> list[SourceInvariantViolation]:
    return _audit_error_api_firewall(root) + _audit_error_semantic_authority(root)


__all__ = ["audit_error_invariants"]
