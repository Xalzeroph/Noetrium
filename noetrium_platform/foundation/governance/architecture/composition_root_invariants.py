from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_text, source_tree

from .source_scan import SourceInvariantViolation, is_transient_source_path, violation


def audit_composition_root_imports(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    package = root / "noetrium_platform"
    if not package.exists():
        return rows
    for path in sorted(package.rglob("*.py")):
        if is_transient_source_path(path):
            continue
        if path == package / "composition" / "__init__.py":
            continue
        text = source_text(path)
        if "noetrium_platform.composition" not in text and "from noetrium_platform import composition" not in text:
            continue
        tree = source_tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "noetrium_platform.composition":
                        rows.append(violation(root, path, "composition_root_import_firewall", node.lineno, "production code imports composition root instead of an exact composition submodule"))
            elif isinstance(node, ast.ImportFrom) and node.module == "noetrium_platform":
                if any(alias.name == "composition" for alias in node.names):
                    rows.append(violation(root, path, "composition_root_import_firewall", node.lineno, "production code imports composition root instead of an exact composition submodule"))
    return rows


__all__ = ["audit_composition_root_imports"]
