from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_nodes
from .source_scan import (
    SourceInvariantViolation,
    is_transient_source_path,
    violation,
)


_CANONICAL_SQLITE_IMPLEMENTATION = (
    "noetrium_platform/foundation/kernel/kernel/durability/sqlite.py"
)


# Without type flow, an unqualified name `.rollback()` is not evidence of a
# database write.  Recognize explicit connection receivers; raw BEGIN/COMMIT
# and sqlite3.connect remain separately forbidden independent of the name.
_SQLITE_CONNECTION_NAMES = frozenset({
    "db", "conn", "connection", "db_conn", "sqlite_conn",
    "_db", "_conn", "_connection", "_sqlite_connection",
})


def _sqlite_rollback_receiver(target: ast.Attribute) -> bool:
    receiver = target.value
    if isinstance(receiver, ast.Name):
        return receiver.id in _SQLITE_CONNECTION_NAMES
    if isinstance(receiver, ast.Attribute):
        return receiver.attr in _SQLITE_CONNECTION_NAMES
    return False


def _sqlite_findings(
    path: Path,
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[tuple[int, str], ...]]:
    nodes = source_nodes(path)
    module_aliases: set[str] = set()
    direct_aliases: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sqlite3":
                    module_aliases.add(alias.asname or "sqlite3")
        elif isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
            for alias in node.names:
                if alias.name == "connect":
                    direct_aliases.add(alias.asname or "connect")

    protected_prefixes = (
        "PRAGMA journal_mode",
        "PRAGMA synchronous",
        "PRAGMA busy_timeout",
        "PRAGMA query_only",
        "PRAGMA foreign_keys",
    )
    connects: list[int] = []
    rollbacks: list[int] = []
    policies: list[tuple[int, str]] = []
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name) and target.id in direct_aliases:
            connects.append(node.lineno)
        elif (
            isinstance(target, ast.Attribute)
            and target.attr == "connect"
            and isinstance(target.value, ast.Name)
            and target.value.id in module_aliases
        ):
            connects.append(node.lineno)
        if isinstance(target, ast.Attribute) and target.attr == "rollback" and _sqlite_rollback_receiver(target):
            rollbacks.append(node.lineno)
        if not node.args or not (
            isinstance(target, ast.Attribute)
            and target.attr in {"execute", "executescript"}
        ):
            continue
        first = node.args[0]
        if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
            continue
        statement = first.value.strip()
        upper = statement.upper()
        if upper.startswith("BEGIN"):
            policies.append((node.lineno, upper))
        elif upper in {"COMMIT", "ROLLBACK"}:
            policies.append((node.lineno, upper))
        elif any(statement.startswith(prefix) for prefix in protected_prefixes):
            policies.append((node.lineno, statement.split("=", 1)[0]))
    return tuple(connects), tuple(rollbacks), tuple(policies)


def audit_sqlite_durability_invariants(
    root: Path,
) -> list[SourceInvariantViolation]:
    """Keep SQLite connection/session mechanics under one Platform authority."""

    root = Path(root).resolve()
    production_roots = tuple(
        root / name for name in ("noetrium_platform", "components", "orchestration")
    )
    rows: list[SourceInvariantViolation] = []
    paths = sorted(
        path
        for production_root in production_roots
        for path in production_root.rglob("*.py")
    )
    for path in paths:
        if is_transient_source_path(path):
            continue
        relative = path.relative_to(root).as_posix()
        if relative == _CANONICAL_SQLITE_IMPLEMENTATION:
            continue
        connect_calls, rollback_calls, session_policy_calls = _sqlite_findings(path)
        for line in connect_calls:
            rows.append(
                violation(
                    root,
                    path,
                    "sqlite_durability_authority",
                    line,
                    (
                        "direct sqlite3.connect() bypasses the canonical Platform "
                        "durability authority; use "
                        "foundation.kernel.kernel.durability.sqlite"
                    ),
                )
            )
        for line in rollback_calls:
            rows.append(
                violation(
                    root,
                    path,
                    "sqlite_durability_authority",
                    line,
                    (
                        "direct SQLite rollback bypasses the canonical Platform "
                        "durability authority; use abort_sqlite_writer() or "
                        "rollback_sqlite_writer()"
                    ),
                )
            )
        for line, primitive in session_policy_calls:
            rows.append(
                violation(
                    root,
                    path,
                    "sqlite_durability_authority",
                    line,
                    (
                        f"raw SQLite durability/transaction policy {primitive!r} bypasses the canonical "
                        "Platform durability authority; use "
                        "foundation.kernel.kernel.durability.sqlite"
                    ),
                )
            )
    return rows


__all__ = ["audit_sqlite_durability_invariants"]
