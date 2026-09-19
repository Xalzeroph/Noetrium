from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, violation


def _store_path_accesses(path: Path) -> tuple[int, ...]:
    if not path.exists():
        return ()
    tree = source_tree(path)
    rows: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr != "path":
            continue
        value = node.value
        if isinstance(value, ast.Attribute) and value.attr in {"store", "state", "_store"}:
            rows.append(node.lineno)
    return tuple(rows)


def audit_service_runtime_invariants(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    runtime_manager = root / "noetrium_platform" / "research" / "execution" / "runtime" / "manager"
    for name in ("service_binding.py", "study_process.py"):
        path = runtime_manager / name
        for line in _store_path_accesses(path):
            rows.append(
                violation(
                    root,
                    path,
                    "service_state_backend_boundary",
                    line,
                    "runtime manager reaches service state-store path; use ServiceStateStorePort",
                )
            )
        if path.exists():
            tree = source_tree(path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in {"store", "adapter", "start_journal"}:
                    rows.append(
                        violation(
                            root,
                            path,
                            "service_runtime_encapsulation",
                            node.lineno,
                            f"runtime manager reaches Service OS internal attribute {node.attr}; depend on ExactServiceRuntimePort",
                        )
                    )

    quiescence = root / "noetrium_platform" / "infrastructure" / "lifecycle" / "service" / "runtime" / "quiescence.py"
    if quiescence.exists():
        tree = source_tree(quiescence)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"store", "adapter", "start_journal"}:
                rows.append(
                    violation(
                        root,
                        quiescence,
                        "service_runtime_encapsulation",
                        node.lineno,
                        f"quiescence probe reaches mutable supervisor internals {node.attr}; use ExactServiceRuntimePort",
                    )
                )

    # Runtime Manager may consume only the semantic ExactServiceRuntimePort.
    # Raw Service OS supervisor state/phase/journal inspection is an internal ABI.
    for path in runtime_manager.glob("*.py"):
        if not path.exists():
            continue
        tree = source_tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("noetrium_platform.infrastructure.lifecycle.service.runtime"):
                forbidden_names = {"ServicePhase", "ServiceSupervisorState", "ServiceStartIntent", "ExactServiceSupervisor"}
                for alias in node.names:
                    if alias.name in forbidden_names:
                        rows.append(
                            violation(
                                root,
                                path,
                                "service_external_runtime_boundary",
                                node.lineno,
                                f"runtime manager imports Service OS internal runtime type {alias.name}; depend on ExactServiceRuntimePort semantic outcomes",
                            )
                        )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"observe_state", "unresolved_start"}:
                rows.append(
                    violation(
                        root,
                        path,
                        "service_external_runtime_boundary",
                        node.lineno,
                        f"runtime manager calls internal Service OS inspection verb {node.func.attr}; use reconcile/start/verify_ready semantic endpoint",
                    )
                )
    return rows


__all__ = ["audit_service_runtime_invariants"]
