#!/usr/bin/env python3
"""Select tests owned by the temporary in-repository research workspace.

Ownership is derived from dependencies, not filename prefixes. Platform tests may
contain words such as "research" or "scientific" without depending on paper
reproductions and must remain outside this workspace suite.

For stacked research PRs, affected-test selection is derived from the exact Git
base/head diff. The integration PR to main still runs the complete workspace
suite, so focused child PRs can be independently green without weakening the
full research baseline.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]

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


def _test_source(path: Path) -> tuple[str, tuple[str, ...]]:
    source = path.read_text(encoding="utf-8-sig")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise RuntimeError(f"cannot classify invalid test source {path}: {exc}") from exc
    return source.replace("\\", "/"), _import_modules(tree)


def is_workspace_test(path: Path) -> bool:
    source, modules = _test_source(path)
    if any(_module_is_workspace_owned(module) for module in modules):
        return True
    return any(token in source for token in _WORKSPACE_PATH_LITERALS)


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


def _changed_paths(base_sha: str, root: Path = ROOT) -> tuple[str, ...]:
    if not base_sha or any(char.isspace() for char in base_sha):
        raise ValueError("affected-test base SHA must be non-empty canonical text")
    completed = subprocess.run(
        ["git", "diff", "--name-only", f"{base_sha}...HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "cannot resolve stacked-PR change set: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )
    return tuple(
        row.strip().replace("\\", "/")
        for row in completed.stdout.splitlines()
        if row.strip()
    )


def _module_for_python_path(path: str) -> str | None:
    if not path.endswith(".py"):
        return None
    module = path[:-3].replace("/", ".")
    if module.endswith(".__init__"):
        module = module[: -len(".__init__")]
    return module or None


def _dependency_needles(path: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return module-prefix and source-path needles for one changed workspace file."""
    modules: list[str] = []
    paths: list[str] = []

    module = _module_for_python_path(path)
    if module is not None and (
        path.startswith("research/reproductions/")
        or path.startswith("research/benchmarks/")
        or path.startswith("benchmarks/")
        or path.startswith("scripts/sync_")
    ):
        modules.append(module)

    if path.startswith("research/reproductions/"):
        parts = path.split("/")
        if len(parts) >= 3:
            package = parts[2]
            modules.append(f"research.reproductions.{package}")
            paths.append(f"research/reproductions/{package}/")
    elif path.startswith("research/benchmarks/"):
        parts = path.split("/")
        if len(parts) >= 3:
            stem = parts[2].removesuffix(".py")
            if stem and stem != "__init__":
                modules.append(f"research.benchmarks.{stem}")
            paths.append("research/benchmarks/")
    elif path.startswith("benchmarks/"):
        paths.append("benchmarks/")
    elif path.startswith("research/catalog/"):
        paths.append(path)
        paths.append("research/catalog/")

    return tuple(dict.fromkeys(modules)), tuple(dict.fromkeys(paths))


def affected_workspace_tests(
    base_sha: str,
    root: Path = ROOT,
) -> tuple[Path, ...]:
    owned = workspace_tests(root)
    owned_by_relative = {
        path.relative_to(root).as_posix(): path
        for path in owned
    }
    changed = _changed_paths(base_sha, root)

    affected: set[Path] = set()
    module_needles: set[str] = set()
    path_needles: set[str] = set()

    for changed_path in changed:
        direct = owned_by_relative.get(changed_path)
        if direct is not None:
            affected.add(direct)
        modules, paths = _dependency_needles(changed_path)
        module_needles.update(modules)
        path_needles.update(paths)

    if not module_needles and not path_needles:
        return tuple(sorted(affected))

    for test in owned:
        source, imports = _test_source(test)
        if any(
            imported == needle or imported.startswith(needle + ".")
            for imported in imports
            for needle in module_needles
        ):
            affected.add(test)
            continue
        if any(needle in source for needle in path_needles):
            affected.add(test)

    return tuple(sorted(affected))


def _run(rows: tuple[Path, ...], root: Path = ROOT) -> int:
    if not rows:
        print("RESEARCH_WORKSPACE_AFFECTED_TESTS_PASS files=0")
        return 0
    relative = _relative(rows, root)
    print(
        "RESEARCH_WORKSPACE_TEST_RUN "
        f"files={len(relative)} "
        + " ".join(relative)
    )
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *relative],
        cwd=root,
        check=False,
    ).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("check")
    sub.add_parser("run")
    affected_list = sub.add_parser("list-affected")
    affected_list.add_argument("base_sha")
    affected_run = sub.add_parser("run-affected")
    affected_run.add_argument("base_sha")
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

    if args.command == "run":
        return _run(rows)

    affected = affected_workspace_tests(args.base_sha, ROOT)
    if args.command == "list-affected":
        print("\n".join(_relative(affected, ROOT)))
        return 0
    return _run(affected)


if __name__ == "__main__":
    raise SystemExit(main())
