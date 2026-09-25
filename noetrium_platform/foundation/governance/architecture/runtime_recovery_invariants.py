from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, imports, violation


def _class_methods(path: Path, class_name: str) -> tuple[tuple[str, int], ...]:
    if not path.exists():
        return ()
    tree = source_tree(path)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return tuple(
                (child.name, child.lineno)
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
    return ()


def audit_runtime_recovery_invariants(root: Path) -> list[SourceInvariantViolation]:
    runtime = root / "noetrium_platform" / "research" / "execution" / "runtime" / "manager"
    rows: list[SourceInvariantViolation] = []

    store = root / "noetrium_platform" / "infrastructure" / "reliability" / "recovery" / "providers" / "lease_store.py"
    for method, line in _class_methods(store, "RecoveryLeaseStore"):
        if method == "execution":
            rows.append(violation(
                root, store, "recovery_execution_authority", line,
                "durable RecoveryLeaseStore owns execution fencing; use RecoveryExecutionFactoryPort",
            ))

    one_click = runtime / "one_click.py"
    for module, line in imports(one_click) if one_click.exists() else ():
        if module in {
            "noetrium_platform.infrastructure.reliability.recovery.providers.lease_store",
            "noetrium_platform.infrastructure.reliability.recovery.execution.runtime.file_lock",
        }:
            rows.append(violation(
                root, one_click, "recovery_execution_authority", line,
                f"OneClickRuntimeManager imports concrete recovery backend {module}; depend on recovery ports",
            ))

    execution = (
        root
        / "noetrium_platform"
        / "reliability"
        / "recovery"
        / "execution"
        / "runtime"
        / "file_lock.py"
    )
    for module, line in imports(execution) if execution.exists() else ():
        if module.endswith("recovery_lease_store"):
            rows.append(violation(
                root, execution, "recovery_execution_authority", line,
                "execution-fence backend imports concrete lease store; depend on RecoveryLeaseStatePort",
            ))
    return rows


__all__ = ["audit_runtime_recovery_invariants"]
