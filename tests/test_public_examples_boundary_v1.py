from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_downstream_examples_use_only_public_noetrium_surfaces() -> None:
    violations: list[str] = []
    for path in sorted((ROOT / "examples").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("noetrium_platform"):
                        violations.append(
                            f"{path.relative_to(ROOT)}:{node.lineno}: import {alias.name}"
                        )
            if module and module.startswith("noetrium_platform"):
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: from {module} import ..."
                )
    assert violations == []


def test_downstream_documentation_does_not_teach_private_imports() -> None:
    violations: list[str] = []
    for path in sorted((ROOT / "docs").rglob("*.md")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("from noetrium_platform.") or stripped.startswith("import noetrium_platform."):
                violations.append(f"{path.relative_to(ROOT)}:{line_number}: {stripped}")
    for path in sorted(ROOT.glob("README*.md")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("from noetrium_platform.") or stripped.startswith("import noetrium_platform."):
                violations.append(f"{path.relative_to(ROOT)}:{line_number}: {stripped}")
    assert violations == []
