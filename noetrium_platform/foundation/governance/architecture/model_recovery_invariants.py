from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, imports, violation


def audit_model_recovery_observability_boundary(root: Path) -> list[SourceInvariantViolation]:
    runner = root / "noetrium_platform" / "capabilities" / "model" / "serving" / "runtime" / "durable_recovery.py"
    if not runner.exists():
        return []
    rows: list[SourceInvariantViolation] = []
    forbidden_prefixes = (
        "noetrium_platform.evidence.observability.api", "noetrium_platform.evidence.observability.telemetry", "noetrium_platform.infrastructure.reliability.forensics",
    )
    for module, line in imports(runner):
        if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden_prefixes):
            rows.append(violation(root, runner, "model_recovery_observability_boundary", line, f"model recovery state machine imports observability/control plane {module}; emit lifecycle callbacks through DurableRecoveryObserverPort"))
    tree = source_tree(runner)
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        value = node.func.value
        if not (isinstance(value, ast.Attribute) and value.attr == "observer"):
            continue
        cursor: ast.AST | None = node
        isolated = False
        while cursor in parents:
            cursor = parents[cursor]
            if isinstance(cursor, ast.Lambda):
                isolated = True
                break
        if not isolated:
            rows.append(violation(root, runner, "model_recovery_observer_isolation", node.lineno, "model recovery invokes observer directly; route delivery through fail-isolated _notify"))
    return rows


__all__ = ["audit_model_recovery_observability_boundary"]
