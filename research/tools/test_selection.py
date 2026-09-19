#!/usr/bin/env python3
"""Select tests owned by the temporary in-repository research workspace.

Ownership is derived from dependencies, not filename prefixes. Platform tests may
contain words such as "research" or "scientific" without depending on paper
reproductions and must remain outside this workspace suite.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = ROOT / "tests"

_WORKSPACE_MODULE_PREFIXES = (
    "research",
    "benchmarks",
)
_WORKSPACE_SYNC_MODULES = frozenset({
    "scripts.sync_benchmark_manifests",
    "scripts.sync_reproductions",
    "scripts.sync_publication_priority",
    "scripts.sync_research_pressure",
    "scripts.sync_research_program",
    "scripts.sync_lineage_status",
})
_WORKSPACE_PATH_LITERALS = (
    "research/reproductions/",
    "research/catalog/",
    "benchmarks/",
)


def _import_modules(tree: ast.AST) -> tuple[str, ...]:
    rows: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            rows.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            rows.append(node.module)
    return tuple(rows)


def _module_is_workspace_owned(module: str) -> bool:
    if module in _WORKSPACE_SYNC_MODULES:
        return True
    return any(
        module == prefix or module.startswith(prefix + ".")
        for prefix in _WORKSPACE_MODULE_PREFIXES
    )


def is_workspace_test(path: Path) -> bool:
    source = path.read_text(encoding="utf-8-sig")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise RuntimeError(f"cannot classify invalid test source {path}: {exc}") from exc

    if any(_module_is_workspace_owned(module) for module in _import_modules(tree)):
        return True

    normalized = source.replace("\\", "/")
    return any(token in normalized for token in _WORKSPACE_PATH_LITERALS)


def workspace_tests(root: Path = ROOT) -> tuple[Path, ...]:
    rows = tuple(
        path
        for path in sorted((root / "tests").glob("test_*.py"))
        if is_workspace_test(path)
    )
    if not rows:
        raise RuntimeError("research workspace test selection is empty")
    return rows


def _relative(rows: tuple[Path, ...], root: Path) -> tuple[str, ...]:
    return tuple(path.relative_to(root).as_posix() for path in rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("check")
    sub.add_parser("run")
    args = parser.parse_args(argv)

    rows = workspace_tests(ROOT)
    relative = _relative(rows, ROOT)

    if args.command == "list":
        print("\n".join(relative))
        return 0

    if args.command == "check":
        forbidden = {
            "tests/test_research_campaign_v1.py",
            "tests/test_research_compiler_v1.py",
            "tests/test_scientific_agent_turn_journal_projection_v1.py",
            "tests/test_scientific_agent_turn_machine_facts_v2.py",
            "tests/test_scientific_research_model_roles_v1.py",
        }
        overlap = sorted(forbidden.intersection(relative))
        if overlap:
            raise RuntimeError(
                "platform-owned tests leaked into research workspace selection: "
                + ", ".join(overlap)
            )
        required = {
            "tests/test_scientific_react_alfworld_method_program_v1.py",
            "tests/test_research_pressure_program_assets_v2.py",
        }
        missing = sorted(required.difference(relative))
        if missing:
            raise RuntimeError(
                "research-owned tests missing from workspace selection: "
                + ", ".join(missing)
            )
        print(f"RESEARCH_WORKSPACE_TEST_SELECTION_PASS files={len(relative)}")
        return 0

    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *relative],
        cwd=ROOT,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
