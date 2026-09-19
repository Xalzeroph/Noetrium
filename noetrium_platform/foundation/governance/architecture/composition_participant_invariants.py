from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, violation


def audit_generic_participant_signatures(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    study = root / "noetrium_platform" / "research" / "experimentation" / "experiment"
    checks = (
        (study / "runtime" / "trial_cycle.py", "ExperimentTrialCycleExecutor", "execute"),
        (study / "run_cycle.py", "RunCycleExecutor", "__init__"),
    )
    forbidden = {"method_session", "environment_session", "agent_session", "capability_sessions"}
    for path, class_name, method_name in checks:
        if not path.exists():
            continue
        tree = source_tree(path)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name != class_name:
                continue
            method = next((child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name), None)
            if method is None:
                continue
            args = {arg.arg for arg in (*method.args.args, *method.args.kwonlyargs)}
            leaked = sorted(args & forbidden)
            if leaked:
                rows.append(violation(
                    root, path, "generic_participant_execution_signature", method.lineno,
                    f"topology-generic execution core reintroduced fixed participant session args: {leaked}",
                ))
    return rows


__all__ = ["audit_generic_participant_signatures"]
