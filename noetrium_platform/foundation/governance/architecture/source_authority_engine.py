from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

from .source_authority_contracts import SourceAuthorityRule, SourceAuthorityViolation
from .source_authority_matchers import resolved_symbol_name
from .source_index import source_nodes, source_tree


def module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def is_production_python(root: Path, path: Path) -> bool:
    relative = path.relative_to(root)
    if any(
        part in {"tests", "__pycache__", ".git", ".venv", "venv", "build", "dist"}
        for part in relative.parts
    ):
        return False
    return bool(relative.parts) and relative.parts[0] in {
        "noetrium_platform",
        "noetrium",
        "projects",
        "components",
        "orchestration",
    }


def _annotation_node_ids(tree: ast.AST) -> frozenset[int]:
    """Return AST nodes that occur only inside Python type annotations."""

    roots: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            roots.append(node.annotation)
        elif isinstance(node, ast.AnnAssign):
            roots.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            roots.append(node.returns)
    return frozenset(id(item) for root in roots for item in ast.walk(root))


def import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    return aliases


def audit_authority_rules(
    root: Path,
    rules: Iterable[SourceAuthorityRule],
) -> tuple[SourceAuthorityViolation, ...]:
    findings: list[SourceAuthorityViolation] = []
    seen: set[tuple[str, str, int]] = set()
    resolved_rules = tuple(rules)
    for path in sorted(root.rglob("*.py")):
        if not is_production_python(root, path):
            continue
        tree = source_tree(path)
        module = module_name(root, path)
        aliases = import_aliases(tree)
        annotation_node_ids = _annotation_node_ids(tree)
        for node in source_nodes(path):
            for rule in resolved_rules:
                if module in rule.allowed_modules:
                    continue
                matched = (
                    isinstance(node, ast.Call) and rule.matches(node, aliases)
                )
                if (
                    not matched
                    and rule.protect_reference
                    and id(node) not in annotation_node_ids
                    and isinstance(node, (ast.Name, ast.Attribute))
                ):
                    matched = resolved_symbol_name(node, aliases) == rule.primitive
                if not matched:
                    continue
                line = int(getattr(node, "lineno", 0))
                key = (rule.authority, module, line)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(SourceAuthorityViolation(
                    authority=rule.authority,
                    primitive=rule.primitive,
                    module=module,
                    path=path.relative_to(root).as_posix(),
                    line=line,
                    allowed_modules=rule.allowed_modules,
                    detail=(
                        f"{rule.primitive} is a protected mutation primitive; "
                        f"authority belongs to {', '.join(rule.allowed_modules)}"
                    ),
                ))
    return tuple(findings)


__all__ = ["audit_authority_rules", "import_aliases", "is_production_python", "module_name"]
