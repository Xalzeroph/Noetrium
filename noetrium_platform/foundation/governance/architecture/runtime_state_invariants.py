from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, imports, violation


def audit_runtime_state_invariants(root: Path) -> list[SourceInvariantViolation]:
    runtime = root / "noetrium_platform" / "research" / "execution" / "runtime" / "manager"
    rows: list[SourceInvariantViolation] = []
    semantic_files = ("state.py", "status_readers.py", "history.py")
    concrete_suffixes = ("runtime_state_storage", "runtime_history_storage")
    for name in semantic_files:
        path = runtime / name
        if not path.exists():
            continue
        for module, line in imports(path):
            if module.endswith(concrete_suffixes):
                rows.append(violation(
                    root, path, "runtime_state_history_backend_boundary", line,
                    f"runtime semantic/status code imports concrete durable backend {module}; depend on ports",
                ))
        tree = source_tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "path":
                rows.append(violation(
                    root, path, "runtime_state_history_backend_boundary", node.lineno,
                    "runtime semantic/status code reaches backend path; use opaque reference() ports",
                ))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "with_name":
                rows.append(violation(
                    root, path, "runtime_state_history_boundary", node.lineno,
                    "runtime control semantics derive sibling durable location; compose stores explicitly",
                ))

    state_coordinator = runtime / "state.py"
    if state_coordinator.exists():
        tree = source_tree(state_coordinator)
        method_calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        if "verified_append_session" not in method_calls:
            rows.append(violation(
                root, state_coordinator, "runtime_history_transaction_boundary", 1,
                "runtime control writes do not hold one verified history append session across state publication",
            ))

    package_root = runtime / "__init__.py"
    for module, line in imports(package_root) if package_root.exists() else ():
        if module.endswith(concrete_suffixes):
            rows.append(violation(
                root, package_root, "runtime_state_history_public_api_boundary", line,
                "runtime_manager package root re-exports concrete runtime state/history backend",
            ))
    return rows


__all__ = ["audit_runtime_state_invariants"]
