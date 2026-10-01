from __future__ import annotations

from pathlib import Path

from noetrium import api
from noetrium_platform.product import research_os as research_os_api

from noetrium_platform.composition.operator.project import project_scaffold
from noetrium_platform.composition.operator.project.project_platform_identity import (
    InstalledPlatformIdentity,
)
from noetrium_platform.composition.operator.project.project_research_os_loader import (
    load_project_research_os,
)
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.product.operator.api import ProjectCreateRequest


_FIXED_PLATFORM = InstalledPlatformIdentity("0.1.0", "a" * 64)


def test_generated_project_shell_accepts_arbitrary_multi_program_research_core(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "paper"
    monkeypatch.setattr(
        project_scaffold,
        "installed_platform_identity",
        lambda: _FIXED_PLATFORM,
    )
    project_scaffold.create_project(
        ProjectCreateRequest("paper", "0.1.0", root)
    )

    core = root / "src" / "paper" / "core.py"
    authored = '''from noetrium import api


def source():
    return {"value": 7}


def consume(payload):
    return {"value": payload["upstream"]["value"] + 1}


def build_research() -> api.ResearchPortfolio:
    portfolio = api.ResearchPortfolioBuilder("paper")
    first = portfolio.programs.create("paper-a")
    first.extensions.define("source", implementation=source)
    first.extensions.node(
        "source",
        definitions=("source",),
        outputs=(("data", "data"),),
    )

    second = portfolio.programs.create("paper-b")
    second.extensions.define("consume", implementation=consume)
    second.extensions.node(
        "consume",
        definitions=("consume",),
        outputs=(("data", "data"),),
    )
    portfolio.handoffs.bind(
        upstream=("paper-a", "source"),
        downstream=("paper-b", "consume"),
        inputs={"upstream": ("data", "data")},
    )
    return portfolio.freeze()


__all__ = ["build_research"]
'''
    core.write_text(authored, encoding="utf-8")

    project_scaffold.sync_project(root)
    assert core.read_text(encoding="utf-8") == authored

    loaded = load_project_research_os(root)
    try:
        assert tuple(program.program_id for program in loaded.portfolio.programs) == (
            "paper-a",
            "paper-b",
        )
        graph = compile_research_portfolio_graph(
            loaded.revision,
            loaded.portfolio,
        )
        assert {node.graph_node_id for node in graph.nodes} == {
            "paper-a::source",
            "paper-b::consume",
        }
        consume = graph.node("paper-b::consume")
        assert consume.upstream_refs == (
            research_os_api.ResearchNodeRef("paper-a", "source"),
        )
        assert len(consume.incoming_edges) == 1
        assert consume.incoming_edges[0].bindings == (
            research_os_api.ResearchInputBinding(
                "upstream",
                "data",
                research_os_api.ResearchValueKind.DATA,
            ),
        )
    finally:
        loaded.close()


def test_generated_project_preserves_public_study_experiment_authoring(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "study-paper"
    monkeypatch.setattr(
        project_scaffold,
        "installed_platform_identity",
        lambda: _FIXED_PLATFORM,
    )
    project_scaffold.create_project(
        ProjectCreateRequest("study-paper", "0.1.0", root)
    )

    core = root / "src" / "study_paper" / "core.py"
    core.write_text(
        '''from noetrium import api


def build_study():
    raise AssertionError("study factory must not execute while loading authoring IR")


def build_research() -> api.ResearchPortfolio:
    portfolio = api.ResearchPortfolioBuilder("study-paper")
    research = portfolio.programs.create("study-paper")
    research.study_protocol("study", implementation=build_study)
    research.experiment("experiment", definitions=("study",))
    return portfolio.freeze()


__all__ = ["build_research"]
''',
        encoding="utf-8",
    )

    project_scaffold.sync_project(root)
    loaded = load_project_research_os(root)
    try:
        program = loaded.portfolio.programs[0]
        assert any(
            definition.kind is research_os_api.ResearchDefinitionKind.PROTOCOL
            for definition in program.definitions
        )
        assert any(
            node.kind is research_os_api.ResearchNodeKind.EXPERIMENT
            for node in program.nodes
        )
    finally:
        loaded.close()
