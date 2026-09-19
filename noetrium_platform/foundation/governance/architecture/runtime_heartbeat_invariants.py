from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, imports, violation


def audit_runtime_heartbeat_invariants(root: Path) -> list[SourceInvariantViolation]:
    runtime = root / "noetrium_platform" / "research" / "execution" / "runtime" / "manager"
    rows: list[SourceInvariantViolation] = []
    for name in ("model_ports.py", "status_readers.py"):
        path = runtime / name
        if not path.exists():
            continue
        for module, line in imports(path):
            if module.endswith("heartbeat_storage"):
                rows.append(violation(
                    root, path, "heartbeat_backend_boundary", line,
                    "runtime semantic/status code imports concrete heartbeat storage; depend on heartbeat ports",
                ))
        tree = source_tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "_path":
                rows.append(violation(
                    root, path, "heartbeat_backend_boundary", node.lineno,
                    "runtime code reaches private heartbeat path layout; use exists/read/reference port methods",
                ))
    package_root = runtime / "__init__.py"
    for module, line in imports(package_root) if package_root.exists() else ():
        if module.endswith("heartbeat_storage"):
            rows.append(violation(
                root, package_root, "heartbeat_public_api_boundary", line,
                "runtime_manager package root re-exports concrete heartbeat backend",
            ))
    return rows


__all__ = ["audit_runtime_heartbeat_invariants"]
