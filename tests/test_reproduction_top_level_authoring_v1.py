from __future__ import annotations

from noetrium import api

from research.reproductions import build_research
from research.reproductions.research_os import (
    discover_reproduction_definitions,
    executable_reproduction_definitions,
    is_research_os_executable,
)


def test_repository_reproductions_use_same_top_level_authoring_contract_as_projects() -> None:
    portfolio = build_research()

    assert isinstance(portfolio, api.ResearchPortfolio)
    assert portfolio.portfolio_id == "repository-reproductions.current-research-os"
    assert portfolio.programs
    assert all(isinstance(program, api.ResearchProgram) for program in portfolio.programs)

    executable = executable_reproduction_definitions()
    assert tuple(program.program_id for program in portfolio.programs) == tuple(
        sorted(definition.package for definition in executable)
    )


def test_every_executable_reproduction_is_reachable_from_top_level_portfolio() -> None:
    executable = executable_reproduction_definitions()
    portfolio = build_research()

    assert len(portfolio.programs) == len(executable)
    assert {program.program_id for program in portfolio.programs} == {
        definition.package for definition in executable
    }


def test_non_executable_catalog_entries_are_never_silently_promoted() -> None:
    definitions = discover_reproduction_definitions()
    portfolio_ids = {program.program_id for program in build_research().programs}

    for definition in definitions:
        if not is_research_os_executable(definition):
            assert definition.package not in portfolio_ids
