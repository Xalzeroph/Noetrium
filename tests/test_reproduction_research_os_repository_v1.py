from __future__ import annotations

import pytest

from noetrium import api
from scripts.run_reproduction_fleet import build_plan

from research.reproductions.research_os import (
    ReproductionResearchOSCompileError,
    bind_reproduction_execution,
    compile_repository_reproduction_portfolio,
    compile_reproduction_research_program,
    discover_reproduction_definitions,
    executable_reproduction_definitions,
    is_research_os_executable,
    materialize_reproduction_method_program,
    resolve_method_program_binding,
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


def test_all_protocol_bound_reproductions_have_only_typed_execution_requirements() -> None:
    plan = build_plan()
    assert plan["compile_failure_count"] == 0
    for row in plan["lanes"]:
        assert row["blockers"] == ()
        parameters = tuple(row["execution_requirement_parameters"])
        kinds = tuple(row["execution_requirement_kinds"])
        digests = tuple(row["execution_requirement_digests"])
        assert len(parameters) == len(kinds) == len(digests)
        assert len(parameters) == len(set(parameters))
        assert all(kind in {
            "benchmark_split",
            "capability_id",
            "capability_closure",
            "paper_option",
        } for kind in kinds)
        assert all(len(digest) == 64 for digest in digests)



def test_toolformer_execution_binding_cannot_drift_from_method_capability_closure() -> None:
    from research.reproductions.toolformer.definition import REPRODUCTION

    capabilities = (
        "tool.question-answering",
        "tool.wikipedia-search",
        "tool.calculator",
        "tool.calendar",
        "tool.machine-translation",
    )
    binding = bind_reproduction_execution(
        REPRODUCTION,
        binding_id="paper-eval",
        study_factory="build_toolformer_study",
        benchmark_id="toolformer-eval",
        values={
            "split_id": "paper-eval",
            "tool_capability_ids": capabilities,
        },
    )
    implementation = materialize_reproduction_method_program(
        REPRODUCTION,
        binding,
    )
    assert implementation is not None
    assert implementation.program_digest == (
        resolve_method_program_binding(REPRODUCTION).program_digest
    )

    with pytest.raises(
        ReproductionResearchOSCompileError,
        match="Study/Method binding disagrees",
    ):
        bind_reproduction_execution(
            REPRODUCTION,
            binding_id="drifted",
            study_factory="build_toolformer_study",
            benchmark_id="toolformer-eval",
            values={
                "split_id": "paper-eval",
                "tool_capability_ids": ("tool.calculator",),
            },
        )


def test_adacm2_preserves_both_paper_interpretations_as_distinct_execution_lanes() -> None:
    from research.reproductions.adacm2_memory.definition import REPRODUCTION

    eq6 = bind_reproduction_execution(
        REPRODUCTION,
        binding_id="lvu-eq6",
        study_factory="build_adacm2_lvu_study",
        benchmark_id="lvu",
        values={"interpretation": "eq6_literal"},
    )
    eq8 = bind_reproduction_execution(
        REPRODUCTION,
        binding_id="lvu-eq8",
        study_factory="build_adacm2_lvu_study",
        benchmark_id="lvu",
        values={"interpretation": "eq8_consistent"},
    )

    assert eq6.binding_digest != eq8.binding_digest
    assert eq6.requirement_digests == eq8.requirement_digests
    assert eq6.values["interpretation"] == "eq6_literal"
    assert eq8.values["interpretation"] == "eq8_consistent"
