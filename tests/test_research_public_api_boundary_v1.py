from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER_SURFACE_ROOTS = (ROOT / "examples",)


def _noetrium_import_violations(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "noetrium" or alias.name.startswith(
                    ("noetrium.", "noetrium_platform", "orchestration")
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
            if module.startswith(("noetrium.", "noetrium_platform", "orchestration")):
                violations.append(f"from {module} import ...")
    return tuple(violations)


def test_user_facing_quickstarts_use_one_module_style_downstream_api() -> None:
    violations: list[str] = []
    checked = 0
    for root in USER_SURFACE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "noetrium" not in text:
                continue
            checked += 1
            for violation in _noetrium_import_violations(path):
                violations.append(f"{path.relative_to(ROOT)}: {violation}")
    assert checked > 0
    assert violations == []


def test_unified_api_is_exactly_the_product_research_os_surface() -> None:
    from noetrium import api
    from noetrium_platform.product import api as product_api

    assert tuple(api.__all__) == tuple(product_api.__all__)
    assert "ResearchOS" in api.__all__
    assert "ResearchProgramBuilder" in api.__all__
    assert not hasattr(api, "catalog")
    assert hasattr(api, "MethodProgram")
    assert hasattr(api, "BenchmarkCutRequirement")
    assert hasattr(api, "requires_benchmark_cut")
