from __future__ import annotations

import ast
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER_SURFACE_ROOTS = (ROOT / "examples",)


def _noetrium_import_violations(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "noetrium":
                    violations.append("import noetrium")
                elif alias.name.startswith(
                    ("noetrium.", "noetrium_platform", "components", "orchestration")
                ):
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "noetrium":
                allowed = {"NoetriumUnit", "run"}
                if (
                    node.level != 0
                    or not node.names
                    or any(
                        alias.name not in allowed or alias.asname is not None
                        for alias in node.names
                    )
                ):
                    rendered = ", ".join(alias.name for alias in node.names)
                    violations.append(f"from noetrium import {rendered}")
                continue
            if module.startswith(
                ("noetrium.", "noetrium_platform", "components", "orchestration")
            ):
                violations.append(f"from {module} import ...")
    return tuple(violations)


def test_user_facing_quickstarts_use_exact_two_symbol_root_import() -> None:
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


def test_unified_api_exposes_exactly_unit_and_run_without_lower_layer_leakage() -> None:
    import noetrium

    assert noetrium.__all__ == ("NoetriumUnit", "run")

    for retired in (
        "ResearchGraphBuilder",
        "MeasurementDefinition",
        "ScientificStatistics",
        "BenchmarkCutRequirement",
        "catalog",
    ):
        assert not hasattr(noetrium, retired)
