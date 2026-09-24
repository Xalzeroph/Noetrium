from __future__ import annotations

from research.reproductions.contracts import ReproductionLifecycle
from research.reproductions.research_os import (
    compile_reproduction_research_program,
    discover_reproduction_definitions,
    executable_reproduction_definitions,
)


def test_reproduction_research_os_migration_coverage_is_authority_derived() -> None:
    definitions = discover_reproduction_definitions()
    assert len(definitions) == 100

    by_lifecycle = {
        lifecycle: tuple(
            row for row in definitions if row.lifecycle is lifecycle
        )
        for lifecycle in ReproductionLifecycle
    }
    assert len(by_lifecycle[ReproductionLifecycle.PROTOCOL_BOUND]) == 91
    assert len(by_lifecycle[ReproductionLifecycle.CATALOGUED]) == 8
    assert len(by_lifecycle[ReproductionLifecycle.ARTIFACT_ONLY]) == 1
    assert sum(len(rows) for rows in by_lifecycle.values()) == 100

    executable = executable_reproduction_definitions()
    executable_packages = {row.package for row in executable}
    protocol_bound = by_lifecycle[ReproductionLifecycle.PROTOCOL_BOUND]
    missing = tuple(
        sorted(
            row.package
            for row in protocol_bound
            if row.package not in executable_packages
        )
    )
    assert missing == ()

    compiled = tuple(
        compile_reproduction_research_program(row)
        for row in protocol_bound
    )
    assert tuple(program.program_id for program in compiled) == tuple(
        sorted(row.package for row in protocol_bound)
    )
    assert len({program.program_id for program in compiled}) == 91


def test_non_execution_lifecycles_are_not_silently_promoted() -> None:
    definitions = discover_reproduction_definitions()
    protocol_packages = {
        row.package
        for row in definitions
        if row.lifecycle is ReproductionLifecycle.PROTOCOL_BOUND
    }
    assert protocol_packages

    for row in definitions:
        if row.lifecycle in {
            ReproductionLifecycle.CATALOGUED,
            ReproductionLifecycle.ARTIFACT_ONLY,
            ReproductionLifecycle.PAPER_ONLY,
        }:
            assert row.package not in protocol_packages
