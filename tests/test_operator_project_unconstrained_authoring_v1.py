from __future__ import annotations

from pathlib import Path

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
    first = api.ResearchProgramBuilder("paper-a")
    first.definition(
        "source",
        kind=api.ResearchDefinitionKind.CUSTOM,
        implementation=source,
    )
    first.node(
        "source",
        kind=api.ResearchNodeKind.CUSTOM,
        definitions=("source",),
        outputs=(api.ResearchOutputSpec("data", api.ResearchValueKind.DATA),),
    )

    second = api.ResearchProgramBuilder("paper-b")
    second.definition(
        "consume",
        kind=api.ResearchDefinitionKind.CUSTOM,
        implementation=consume,
    )
    second.node(
        "consume",
        kind=api.ResearchNodeKind.CUSTOM,
        definitions=("consume",),
        outputs=(api.ResearchOutputSpec("data", api.ResearchValueKind.DATA),),
    )

    dependency = api.ResearchPortfolioDependency(
        api.ResearchNodeRef("paper-a", "source"),
        api.ResearchNodeRef("paper-b", "consume"),
        (
            api.ResearchInputBinding(
                "upstream",
                "data",
                api.ResearchValueKind.DATA,
            ),
        ),
    )
    return api.ResearchPortfolio(
        "paper",
        (first.freeze(), second.freeze()),
        (dependency,),
    )


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
        assert consume.node.depends_on == (
            api.ResearchDependency(
                api.ResearchNodeRef("paper-a", "source"),
                (
                    api.ResearchInputBinding(
                        "upstream",
                        "data",
                        api.ResearchValueKind.DATA,
                    ),
                ),
            ),
        )
    finally:
        loaded.close()
