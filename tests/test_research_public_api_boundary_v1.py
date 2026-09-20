from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOWNSTREAM_RESEARCH_ROOTS = (
    ROOT / "research" / "authoring",
    ROOT / "research" / "benchmarks",
    ROOT / "research" / "reproductions",
)


def _noetrium_import_violations(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "noetrium" or alias.name.startswith(
                    ("noetrium.", "noetrium_platform", "components", "orchestration")
                ):
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "noetrium":
                if (
                    node.level != 0
                    or len(node.names) != 1
                    or node.names[0].name != "api"
                    or node.names[0].asname is not None
                ):
                    rendered = ", ".join(alias.name for alias in node.names)
                    violations.append(f"from noetrium import {rendered}")
                continue
            if module.startswith(
                ("noetrium.", "noetrium_platform", "components", "orchestration")
            ):
                violations.append(f"from {module} import ...")
    return tuple(violations)


def test_research_workspace_uses_one_module_style_downstream_api() -> None:
    violations: list[str] = []
    for root in DOWNSTREAM_RESEARCH_ROOTS:
        for path in sorted(root.rglob("*.py")):
            for violation in _noetrium_import_violations(path):
                violations.append(f"{path.relative_to(ROOT)}: {violation}")
    assert violations == []


def test_unified_api_is_the_declared_catalog_entrypoint() -> None:
    from noetrium import api

    assert api.catalog().entrypoint == "noetrium.api"
