from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, imports, violation


_STATE_AUTHORITIES = (
    "supervisor.py",
    "start_coordination.py",
    "state_transition.py",
    "quiescence.py",
    "status_reader.py",
)


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


def audit_service_state_invariants(root: Path) -> list[SourceInvariantViolation]:
    service_os = root / "noetrium_platform" / "infrastructure" / "lifecycle" / "service" / "runtime"
    rows: list[SourceInvariantViolation] = []

    old_state = service_os / "state.py"
    if old_state.exists():
        rows.append(
            violation(
                root,
                old_state,
                "service_state_backend_boundary",
                1,
                "legacy service_os.state backend façade exists; service state contracts/ports/storage must remain separate",
            )
        )

    for name in _STATE_AUTHORITIES:
        path = service_os / name
        if not path.exists():
            continue
        for module, line in imports(path):
            if module.endswith("state_storage") or module == "pathlib":
                rows.append(
                    violation(
                        root,
                        path,
                        "service_state_backend_boundary",
                        line,
                        f"service runtime authority imports concrete state backend {module}; depend on ServiceStateStorePort",
                    )
                )
        for line in _store_path_accesses(path):
            rows.append(
                violation(
                    root,
                    path,
                    "service_state_backend_boundary",
                    line,
                    "service runtime authority reaches state-store path; use exists/read/write/reference port methods",
                )
            )

    package_root = service_os / "__init__.py"
    for module, line in imports(package_root) if package_root.exists() else ():
        if module.endswith("state_storage"):
            rows.append(
                violation(
                    root,
                    package_root,
                    "service_state_public_api_boundary",
                    line,
                    "service_os package root re-exports concrete state backend",
                )
            )
    return rows


__all__ = ["audit_service_state_invariants"]
