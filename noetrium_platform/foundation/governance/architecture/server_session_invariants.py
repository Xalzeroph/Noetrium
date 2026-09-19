from __future__ import annotations

from pathlib import Path

from .source_index import source_tree
import ast

from .source_scan import SourceInvariantViolation, imports, violation


def _forbid_imports(
    root: Path,
    path: Path,
    forbidden: tuple[str, ...],
    invariant: str,
    reason: str,
) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    if not path.exists():
        return rows
    for module, line in imports(path):
        if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
            rows.append(violation(root, path, invariant, line, f"{reason}: {module}"))
    return rows


def audit_server_session_invariants(root: Path) -> list[SourceInvariantViolation]:
    base = root / "noetrium_platform"
    rows: list[SourceInvariantViolation] = []

    # Reconciliation/status logic must depend on the binding-store port, never
    # on the filesystem implementation. This is what keeps SQLite/etcd/etc.
    # replaceable without changing session semantics.
    for name in ("manager.py", "status.py"):
        rows += _forbid_imports(
            root,
            base / "runtime" / "session" / "runtime" / name,
            ("noetrium_platform.infrastructure.lifecycle.session.runtime.binding", ".binding"),
            "persistent_session_binding_store_boundary",
            "persistent-session runtime logic imports concrete binding storage",
        )

    # Runtime orchestration sees only the API. A tmux/systemd backend is chosen
    # by a composition root, not by Runtime Manager.
    rows += _forbid_imports(
        root,
        base / "runtime" / "server" / "lifecycle" / "runtime" / "bootstrap.py",
        ("noetrium_platform.infrastructure.lifecycle.session.runtime", "noetrium_platform.infrastructure.lifecycle.launch_control"),
        "persistent_session_runtime_boundary",
        "server lifecycle bootstrap imports persistent-session implementation",
    )

    # Backend-neutral manager must never grow backend-specific branching.
    manager = base / "runtime" / "session" / "runtime" / "manager.py"
    if manager.exists():
        tree = source_tree(manager)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            values = [node.left, *node.comparators]
            if any(
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and value.value.lower() in {"tmux", "systemd"}
                for value in values
            ):
                rows.append(violation(
                    root,
                    manager,
                    "persistent_session_backend_neutrality",
                    node.lineno,
                    "PersistentSessionManager branches on a concrete backend id",
                ))
    return rows


__all__ = ["audit_server_session_invariants"]
