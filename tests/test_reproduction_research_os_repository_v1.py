from __future__ import annotations

from noetrium import api
from scripts.run_reproduction_fleet import build_plan

from research.reproductions.research_os import (
    compile_repository_reproduction_portfolio,
    compile_reproduction_research_program,
    discover_reproduction_definitions,
    executable_reproduction_definitions,
    is_research_os_executable,
)


def test_every_execution_bearing_reproduction_compiles_to_current_research_os() -> None:
    definitions = discover_reproduction_definitions()
    assert len(definitions) >= 100
    assert tuple(row.package for row in definitions) == tuple(
        sorted(row.package for row in definitions)
    )

    executable = executable_reproduction_definitions()
    assert executable
    failures: list[tuple[str, str]] = []
    programs: list[api.ResearchProgram] = []
    for definition in executable:
        try:
            program = compile_reproduction_research_program(definition)
        except BaseException as exc:  # aggregate every stale reproduction in one CI result
            failures.append(
                (definition.package, f"{type(exc).__name__}: {exc}")
            )
            continue
        programs.append(program)
        assert program.program_id == definition.package
        assert is_research_os_executable(definition)

    assert failures == []
    assert len(programs) == len(executable)
    assert len({program.program_id for program in programs}) == len(programs)


def test_all_executable_reproductions_share_one_current_research_os_portfolio() -> None:
    executable = executable_reproduction_definitions()
    portfolio = compile_repository_reproduction_portfolio()

    assert tuple(program.program_id for program in portfolio.programs) == tuple(
        sorted(row.package for row in executable)
    )
    assert len(portfolio.programs) == len(executable)
    assert len({program.program_id for program in portfolio.programs}) == len(
        portfolio.programs
    )


def test_catalog_only_reproductions_are_not_silently_promoted_to_executable() -> None:
    definitions = discover_reproduction_definitions()
    non_executable = tuple(
        row for row in definitions if not is_research_os_executable(row)
    )
    assert non_executable
    executable_packages = {
        row.package for row in executable_reproduction_definitions()
    }
    assert not executable_packages.intersection(
        row.package for row in non_executable
    )


def test_all_protocol_bound_reproductions_have_exact_execution_bindings() -> None:
    plan = build_plan()
    unresolved = tuple(
        (
            row["package"],
            tuple(row["unresolved_study_parameters"]),
            tuple(row["blockers"]),
        )
        for row in plan["lanes"]
        if row["unresolved_study_parameters"] or row["blockers"]
    )
    assert unresolved == ()
