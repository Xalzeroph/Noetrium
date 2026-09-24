from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree
from .source_scan import (
    SourceInvariantViolation,
    is_transient_source_path,
    violation,
)


_CANONICAL_SQLITE_IMPLEMENTATION = (
    "noetrium_platform/foundation/kernel/kernel/durability/sqlite.py"
)


def _sqlite_connect_calls(path: Path) -> tuple[int, ...]:
    tree = source_tree(path)
    module_aliases: set[str] = set()
    direct_aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sqlite3":
                    module_aliases.add(alias.asname or "sqlite3")
        elif isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
            for alias in node.names:
                if alias.name == "connect":
                    direct_aliases.add(alias.asname or "connect")

    rows: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name) and target.id in direct_aliases:
            rows.append(node.lineno)
            continue
        if (
            isinstance(target, ast.Attribute)
            and target.attr == "connect"
            and isinstance(target.value, ast.Name)
            and target.value.id in module_aliases
        ):
            rows.append(node.lineno)
    return tuple(rows)


def _sqlite_session_policy_calls(path: Path) -> tuple[tuple[int, str], ...]:
    """Find raw SQLite durability/transaction policy outside the canonical primitive."""
    tree = source_tree(path)
    protected_prefixes = (
        "PRAGMA journal_mode",
        "PRAGMA synchronous",
        "PRAGMA busy_timeout",
        "PRAGMA query_only",
        "PRAGMA foreign_keys",
    )
    rows: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        target = node.func
        if not (
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
            rows.append((node.lineno, upper))
            continue
        if upper in {"COMMIT", "ROLLBACK"}:
            rows.append((node.lineno, upper))
            continue
        if any(statement.startswith(prefix) for prefix in protected_prefixes):
            rows.append((node.lineno, statement.split("=", 1)[0]))
    return tuple(rows)


def audit_sqlite_durability_invariants(
    root: Path,
) -> list[SourceInvariantViolation]:
    """Keep SQLite connection/session mechanics under one Platform authority."""

    root = Path(root).resolve()
    package = root / "noetrium_platform"
    rows: list[SourceInvariantViolation] = []
    for path in sorted(package.rglob("*.py")):
        if is_transient_source_path(path):
            continue
        relative = path.relative_to(root).as_posix()
        if relative == _CANONICAL_SQLITE_IMPLEMENTATION:
            continue
        for line in _sqlite_connect_calls(path):
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
        for line, primitive in _sqlite_session_policy_calls(path):
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
