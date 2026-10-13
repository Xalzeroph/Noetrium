from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .source_index import source_imports, source_tree


@dataclass(frozen=True, slots=True)
class SourceInvariantViolation:
    invariant: str
    path: str
    line: int
    detail: str


def imports(path: Path) -> tuple[tuple[str, int], ...]:
    return source_imports(path)


def is_transient_source_path(path: Path) -> bool:
    """Exclude synchronization and bytecode staging paths from source audits."""

    return any(
        part.startswith(".rsync-") or part in {
            "__pycache__", ".git", ".venv", "venv", "node_modules",
            ".pytest_cache", ".local", ".server-state", "build", "dist",
        }
        for part in path.parts
    )


def method_calls(path: Path, function_name: str) -> tuple[tuple[str, int], ...]:
    tree = source_tree(path)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) or child.name != function_name:
                continue
            return tuple(
                (item.func.attr, item.lineno)
                for item in ast.walk(child)
                if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
            )
    return ()


def violation(
    root: Path,
    path: Path | str,
    invariant: str,
    line: int,
    detail: str,
) -> SourceInvariantViolation:
    if isinstance(path, Path):
        resolved = path.relative_to(root) if path.is_absolute() else path
        relative = resolved.as_posix()
    else:
        relative = str(path).replace("\\", "/")
    return SourceInvariantViolation(invariant, relative, line, detail)
