from __future__ import annotations

from noetrium_platform.product.research_control import ResearchGraphRevision
from noetrium_platform.foundation.kernel.structure import NoetriumUnit

from noetrium_platform.composition.research_execution_graph import (
    compile_research_portfolio_graph,
)

from research.reproductions import build_research
from research.reproductions.research_units import (
    discover_reproduction_definitions,
    executable_reproduction_definitions,
    is_research_executable,
)


def test_repository_reproductions_use_same_top_level_authoring_contract_as_projects() -> None:
    portfolio = build_research()

    assert type(portfolio) is NoetriumUnit
    assert portfolio.unit_id == "repository-reproductions.current-research"
    assert portfolio.units_with_schema("research.program")
    assert all(isinstance(program, NoetriumUnit) for program in portfolio.units_with_schema("research.program"))

    executable = executable_reproduction_definitions()
    assert tuple(program.unit_id for program in portfolio.units_with_schema("research.program")) == tuple(
        sorted(definition.package for definition in executable)
    )


def test_every_executable_reproduction_is_reachable_from_top_level_portfolio() -> None:
    executable = executable_reproduction_definitions()
    portfolio = build_research()

    assert len(portfolio.units_with_schema("research.program")) == len(executable)
    assert {program.unit_id for program in portfolio.units_with_schema("research.program")} == {
        definition.package for definition in executable
    }


def test_non_executable_catalog_entries_are_never_silently_promoted() -> None:
    definitions = discover_reproduction_definitions()
    portfolio_ids = {program.unit_id for program in build_research().units_with_schema("research.program")}

    for definition in definitions:
        if not is_research_executable(definition):
            assert definition.package not in portfolio_ids



def test_top_level_reproduction_portfolio_compiles_as_one_current_research_graph() -> None:
    portfolio = build_research()
    revision = ResearchGraphRevision(
        portfolio.unit_id,
        portfolio.unit_digest,
        (),
        "repository reproduction fleet",
    )

    graph = compile_research_portfolio_graph(revision, portfolio)

    assert graph.research_revision_digest == revision.revision_digest
    assert len(graph.nodes_by_id) == len(portfolio.units_with_schema("research.program"))
    assert set(graph.nodes_by_id) == {
        portfolio.unit_id + "::" + program.unit_id + "::reproduction"
        for program in portfolio.units_with_schema("research.program")
    }
