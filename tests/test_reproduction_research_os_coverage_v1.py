from __future__ import annotations

from research.reproductions.research_os import (
    compile_reproduction_research_program,
    discover_reproduction_definitions,
    executable_reproduction_definitions,
    is_research_os_executable,
)


def test_reproduction_research_os_migration_coverage_is_authority_derived() -> None:
    definitions = discover_reproduction_definitions()
    assert definitions
    assert tuple(row.package for row in definitions) == tuple(
        sorted(row.package for row in definitions)
    )

    executable = executable_reproduction_definitions()
    executable_packages = {row.package for row in executable}
    expected_packages = {
        row.package for row in definitions if is_research_os_executable(row)
    }
    assert executable_packages == expected_packages

    compiled = tuple(
        compile_reproduction_research_program(row)
        for row in executable
    )
    assert tuple(program.program_id for program in compiled) == tuple(
        sorted(executable_packages)
    )
    assert len({program.program_id for program in compiled}) == len(compiled)


def test_non_executable_declarations_are_not_silently_promoted() -> None:
    definitions = discover_reproduction_definitions()
    executable_packages = {
        row.package for row in executable_reproduction_definitions()
    }

    for row in definitions:
        if not is_research_os_executable(row):
            assert row.package not in executable_packages
