from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, imports, violation


def audit_prompt_trace_invariants(root: Path) -> list[SourceInvariantViolation]:
    trace = root / "noetrium_platform" / "capabilities" / "model" / "request" / "prompt" / "runtime" / "trace.py"
    if not trace.exists():
        return []
    rows: list[SourceInvariantViolation] = []
    forbidden = (
            "noetrium_platform.evidence.observability.telemetry",
        "noetrium_platform.infrastructure.reliability.forensics",
        "noetrium_platform.evidence.observability.api",
    )
    for module, line in imports(trace):
        if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
            rows.append(violation(
                root, trace, "prompt_trace_observability_boundary", line,
                f"PromptRequestTrace imports observability backend/control context {module}; use PromptTraceObserverPort",
            ))
    tree = source_tree(trace)
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in {"point_recorded", "summary_recorded"}:
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
                root, trace, "prompt_trace_observer_isolation", node.lineno,
                "PromptRequestTrace invokes observer directly; route delivery through fail-isolated _notify",
            ))
    return rows


__all__ = ["audit_prompt_trace_invariants"]
