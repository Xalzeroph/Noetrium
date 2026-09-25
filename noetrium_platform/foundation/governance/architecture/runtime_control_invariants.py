from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, imports, violation


def audit_runtime_control_invariants(root: Path) -> list[SourceInvariantViolation]:
    runtime = root / "noetrium_platform" / "research" / "execution" / "runtime" / "manager"
    if not runtime.exists():
        return []
    rows: list[SourceInvariantViolation] = []

    controller = runtime / "controller.py"
    if controller.exists():
        for module, line in imports(controller):
            if module in {
                "noetrium_platform.infrastructure.lifecycle.launch_control.state",
                ".state",
            }:
                rows.append(violation(
                    root,
                    controller,
                    "runtime_control_store_boundary",
                    line,
                    "ExactRuntimeController imports concrete RuntimeControlStore; depend on RuntimeControlTransactionPort",
                ))
        tree = source_tree(controller)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "replace":
                rows.append(violation(
                    root,
                    controller,
                    "runtime_control_transition_authority",
                    node.lineno,
                    "ExactRuntimeController mutates RuntimeControlState directly; use runtime_control_transitions",
                ))

    one_click = runtime / "one_click.py"
    if one_click.exists():
        tree = source_tree(one_click)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            chain: list[str] = []
            cursor: ast.AST = node
            while isinstance(cursor, ast.Attribute):
                chain.append(cursor.attr)
                cursor = cursor.value
            if isinstance(cursor, ast.Name):
                chain.append(cursor.id)
            dotted = ".".join(reversed(chain))
            if ".controller.store" in dotted or dotted.endswith("plane.controller"):
                rows.append(violation(
                    root,
                    one_click,
                    "runtime_control_recovery_boundary",
                    node.lineno,
                    "OneClickRuntimeManager pierces control-plane/controller internals; inject RuntimeControlRecoveryPort",
                ))
    return rows


__all__ = ["audit_runtime_control_invariants"]
