from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, imports, violation


def audit_runtime_service_start_invariants(root: Path) -> list[SourceInvariantViolation]:
    service_os = root / "noetrium_platform" / "infrastructure" / "lifecycle" / "service" / "runtime"
    rows: list[SourceInvariantViolation] = []
    for name in ("start_coordination.py", "supervisor.py"):
        path = service_os / name
        if not path.exists():
            continue
        for module, line in imports(path):
            if module.endswith("start_intent_store"):
                rows.append(violation(
                    root, path, "service_start_storage_boundary", line,
                    "service start authority imports concrete intent storage; inject ServiceStartJournal/port",
                ))
        tree = source_tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "with_name":
                rows.append(violation(
                    root, path, "service_start_storage_boundary", node.lineno,
                    "service start authority derives sibling storage path; compose durable stores explicitly",
                ))
    return rows


__all__ = ["audit_runtime_service_start_invariants"]
