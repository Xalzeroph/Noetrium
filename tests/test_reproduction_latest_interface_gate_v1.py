from __future__ import annotations

import ast
from pathlib import Path

from noetrium import api
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)

from research.reproductions import build_research
from research.reproductions.contracts import ReproductionLifecycle
from research.reproductions.research_os import (
    discover_reproduction_definitions,
    executable_reproduction_definitions,
    is_research_os_executable,
)


_NON_EXECUTABLE = {
    ReproductionLifecycle.CATALOGUED,
    ReproductionLifecycle.PAPER_ONLY,
    ReproductionLifecycle.ARTIFACT_ONLY,
}


def _root() -> Path:
    return Path(__file__).resolve().parents[1] / "research" / "reproductions"


def test_all_repository_reproductions_are_visible_from_one_top_level_inventory() -> None:
    definitions = discover_reproduction_definitions()
    package_dirs = tuple(
        sorted(
            path.name
            for path in _root().iterdir()
            if path.is_dir() and (path / "definition.py").is_file()
        )
    )
    assert len(package_dirs) == 100
    assert tuple(row.package for row in definitions) == package_dirs


def test_every_execution_capable_reproduction_enters_the_latest_research_os() -> None:
    definitions = discover_reproduction_definitions()
    executable = executable_reproduction_definitions()
    expected = tuple(
        row.package for row in definitions if is_research_os_executable(row)
    )
    assert tuple(row.package for row in executable) == expected

    portfolio = build_research()
    assert isinstance(portfolio, api.ResearchPortfolio)
    assert tuple(program.program_id for program in portfolio.programs) == expected

    revision = api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "latest-interface reproduction fleet gate",
    )
    graph = compile_research_portfolio_graph(revision, portfolio)
    assert len(graph.nodes) == len(expected)
    assert {node.graph_node_id for node in graph.nodes} == {
        package + "::reproduction" for package in expected
    }


def test_non_executable_reproductions_are_explicit_not_silent_downgrades() -> None:
    definitions = discover_reproduction_definitions()
    non_executable = tuple(
        row for row in definitions if not is_research_os_executable(row)
    )
    assert non_executable
    assert all(row.lifecycle in _NON_EXECUTABLE for row in non_executable)
    runnable_ids = {program.program_id for program in build_research().programs}
    assert not runnable_ids.intersection(row.package for row in non_executable)


def test_reproduction_packages_use_only_public_noetrium_surface() -> None:
    violations: list[str] = []
    for path in sorted(_root().glob("*/*.py")):
        # Only paper-owned package modules are downstream code. Repository-level
        # reproduction compiler/contracts live directly under _root() and are
        # platform/workspace infrastructure, so this glob intentionally excludes them.
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules = (() if node.module is None else (node.module,))
            else:
                continue
            forbidden = False
            if isinstance(node, ast.ImportFrom) and node.module == "noetrium":
                forbidden = any(alias.name != "api" for alias in node.names)
            for module in modules:
                if module in {
                    "components",
                    "orchestration",
                    "noetrium_platform",
                }:
                    forbidden = True
                elif module.startswith(
                    ("components.", "orchestration.", "noetrium_platform.")
                ):
                    forbidden = True
                elif module == "noetrium":
                    forbidden = forbidden or isinstance(node, ast.Import)
                elif (
                    module.startswith("noetrium.")
                    and module != "noetrium.api"
                ):
                    forbidden = True
            if forbidden:
                violations.append(path.relative_to(_root()).as_posix())
                break
    assert violations == []


def test_no_reproduction_restores_a_second_platform_execution_entrypoint() -> None:
    forbidden_names = {
        "application.py",
        "runtime_adapter.py",
        "research_os_adapter.py",
        "platform_adapter.py",
    }
    violations = tuple(
        sorted(
            path.relative_to(_root()).as_posix()
            for path in _root().glob("*/*.py")
            if path.name in forbidden_names
        )
    )
    assert violations == ()
