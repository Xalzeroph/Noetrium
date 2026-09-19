from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, imports, violation


_FORBIDDEN_PREFIXES = (
    "noetrium_platform.evidence.observability.api",
    "noetrium_platform.evidence.observability.telemetry",
    "noetrium_platform.infrastructure.reliability.forensics",
)
_OBSERVER_METHODS = {
    "action_started",
    "action_finished",
    "reconcile_finished",
    "exact_service_started",
    "qualification_verified",
    "lease_wait_started",
    "lease_acquired",
    "lease_conflict",
    "recovery_round",
}


def _audit_observer_delivery(root: Path, path: Path) -> list[SourceInvariantViolation]:
    if not path.exists():
        return []
    rows: list[SourceInvariantViolation] = []
    tree = source_tree(path)
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in _OBSERVER_METHODS:
            continue
        if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "observer"):
            continue
        cursor: ast.AST | None = node
        isolated = False
        while cursor in parents:
            cursor = parents[cursor]
            if isinstance(cursor, ast.Lambda):
                isolated = True
                break
        if not isolated:
            rows.append(violation(
                root,
                path,
                "runtime_observer_isolation",
                node.lineno,
                "runtime state machine invokes observer directly; route delivery through fail-isolated notify_runtime_observer",
            ))
    return rows


def audit_runtime_observability_invariants(root: Path) -> list[SourceInvariantViolation]:
    runtime = root / "noetrium_platform" / "research" / "execution" / "runtime" / "manager"
    if not runtime.exists():
        return []
    rows: list[SourceInvariantViolation] = []
    for name in ("controller.py", "one_click.py", "control_plane.py"):
        path = runtime / name
        if not path.exists():
            continue
        for module, line in imports(path):
            if any(module == prefix or module.startswith(prefix + ".") for prefix in _FORBIDDEN_PREFIXES):
                rows.append(violation(
                    root,
                    path,
                    "runtime_observability_boundary",
                    line,
                    f"runtime truth path imports observability/control-plane implementation {module}; emit lifecycle callbacks through runtime observer ports",
                ))
        rows.extend(_audit_observer_delivery(root, path))
    return rows


__all__ = ["audit_runtime_observability_invariants"]
