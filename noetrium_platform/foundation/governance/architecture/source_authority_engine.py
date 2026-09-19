from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

from .source_authority_contracts import SourceAuthorityRule, SourceAuthorityViolation
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
    return bool(relative.parts) and relative.parts[0] in {"noetrium_platform", "projects"}


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
    resolved_rules = tuple(rules)
    for path in sorted(root.rglob("*.py")):
        if not is_production_python(root, path):
            continue
        tree = source_tree(path)
        module = module_name(root, path)
        aliases = import_aliases(tree)
        for node in source_nodes(path):
            if not isinstance(node, ast.Call):
                continue
            for rule in resolved_rules:
                if not rule.matches(node, aliases) or module in rule.allowed_modules:
                    continue
                findings.append(SourceAuthorityViolation(
                    authority=rule.authority,
                    primitive=rule.primitive,
                    module=module,
                    path=path.relative_to(root).as_posix(),
                    line=node.lineno,
                    allowed_modules=rule.allowed_modules,
                    detail=(
                        f"{rule.primitive} is a protected mutation primitive; "
                        f"authority belongs to {', '.join(rule.allowed_modules)}"
                    ),
                ))
    return tuple(findings)


__all__ = ["audit_authority_rules", "import_aliases", "is_production_python", "module_name"]
