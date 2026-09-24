from __future__ import annotations

import json
from pathlib import Path

import pytest

from noetrium import api
from scripts.run_reproduction_fleet import build_plan

from research.reproductions.research_os import (
    ReproductionResearchOSCompileError,
    bind_reproduction_execution,
    compile_bound_reproduction_research_program,
    compile_repository_reproduction_portfolio,
    compile_reproduction_research_program,
    discover_reproduction_definitions,
    executable_reproduction_definitions,
    is_research_os_executable,
    materialize_reproduction_method_program,
    resolve_benchmark_split_consumers,
    resolve_execution_requirements,
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
            "capability_id",
            "capability_closure",
            "paper_option",
        } for kind in kinds)
        assert all(len(digest) == 64 for digest in digests)



def test_toolformer_execution_binding_uses_only_paper_owned_capability_closure() -> None:
    from research.reproductions.toolformer.definition import REPRODUCTION

    binding = bind_reproduction_execution(
        REPRODUCTION,
        binding_id="paper-eval",
        study_factory="build_toolformer_study",
        benchmark_id="toolformer-eval",
        benchmark_split_id="paper-eval",
        values={},
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
        match="value set drifted",
    ):
        bind_reproduction_execution(
            REPRODUCTION,
            binding_id="drifted",
            study_factory="build_toolformer_study",
            benchmark_id="toolformer-eval",
            benchmark_split_id="paper-eval",
            values={"tool_capability_ids": ("tool.calculator",)},
        )


def test_adacm2_preserves_both_paper_interpretations_as_distinct_execution_lanes() -> None:
    from research.reproductions.adacm2_memory.definition import REPRODUCTION

    eq6 = bind_reproduction_execution(
        REPRODUCTION,
        binding_id="lvu-eq6",
        study_factory="build_adacm2_lvu_eq6_literal_study",
        benchmark_id="lvu",
        values={},
    )
    eq8 = bind_reproduction_execution(
        REPRODUCTION,
        binding_id="lvu-eq8",
        study_factory="build_adacm2_lvu_eq8_consistent_study",
        benchmark_id="lvu",
        values={},
    )

    assert eq6.binding_digest != eq8.binding_digest
    assert eq6.requirement_digests == eq8.requirement_digests == ()
    assert eq6.values == {}
    assert eq8.values == {}



def test_bound_reproduction_lanes_compile_as_distinct_product_programs() -> None:
    from research.reproductions.adacm2_memory.definition import (
        REPRODUCTION as ADACM2,
    )
    from research.reproductions.toolformer.definition import (
        REPRODUCTION as TOOLFORMER,
    )

    eq6 = bind_reproduction_execution(
        ADACM2,
        binding_id="lvu-eq6",
        study_factory="build_adacm2_lvu_eq6_literal_study",
        benchmark_id="lvu",
        values={},
    )
    eq8 = bind_reproduction_execution(
        ADACM2,
        binding_id="lvu-eq8",
        study_factory="build_adacm2_lvu_eq8_consistent_study",
        benchmark_id="lvu",
        values={},
    )
    toolformer = bind_reproduction_execution(
        TOOLFORMER,
        binding_id="paper-eval",
        study_factory="build_toolformer_study",
        benchmark_id="toolformer-eval",
        benchmark_split_id="paper-eval",
        values={},
    )

    programs = (
        compile_bound_reproduction_research_program(ADACM2, eq6),
        compile_bound_reproduction_research_program(ADACM2, eq8),
        compile_bound_reproduction_research_program(TOOLFORMER, toolformer),
    )
    assert tuple(program.program_id for program in programs) == (
        "adacm2_memory.lvu-eq6",
        "adacm2_memory.lvu-eq8",
        "toolformer.paper-eval",
    )
    assert len({program.program_digest for program in programs}) == 3

    portfolio = api.ResearchPortfolio("bound-reproduction-lanes", programs)
    assert len(portfolio.programs) == 3
    assert len(portfolio.portfolio_digest) == 64



def test_every_reproduction_projection_records_current_product_research_os_identity() -> None:
    definitions = discover_reproduction_definitions()
    fleet_plan = build_plan()
    lanes = {row["package"]: row for row in fleet_plan["lanes"]}
    for definition in definitions:
        payload = json.loads(
            Path(
                "research",
                "reproductions",
                definition.package,
                "reproduction.json",
            ).read_text(encoding="utf-8")
        )
        assert payload["schema"] == "noetrium.reproduction.projection.v10"
        projected = payload["research_os"]
        assert projected["surface"] == "noetrium.api"

        if not is_research_os_executable(definition):
            assert projected == {
                "surface": "noetrium.api",
                "execution_state": "not_executable",
                "program_id": None,
                "program_digest": None,
                "benchmark_authority": {
                    "state": "not_applicable",
                    "selection_digests": [],
                    "blockers": [],
                },
                "benchmark_split_axis": {
                    "required": False,
                    "consumers": [],
                },
                "reproduction_closure_state": "not_applicable",
                "execution_authority_state": "not_applicable",
                "materialization_ready": False,
                "execution_requirements": [],
            }
            continue

        program = compile_reproduction_research_program(definition)
        requirements = resolve_execution_requirements(definition)
        split_consumers = resolve_benchmark_split_consumers(definition)
        lane = lanes[definition.package]
        assert projected["program_id"] == program.program_id
        assert projected["program_digest"] == program.program_digest
        assert projected["benchmark_split_axis"] == {
            "required": bool(split_consumers),
            "consumers": list(split_consumers),
        }
        assert projected["execution_state"] == lane["state"]
        assert projected["benchmark_authority"] == {
            "state": lane["benchmark_authority_state"],
            "selection_digests": list(lane["benchmark_selection_digests"]),
            "blockers": list(lane["benchmark_blockers"]),
        }
        assert (
            projected["reproduction_closure_state"]
            == lane["reproduction_closure_state"]
        )
        assert projected["execution_authority_state"] == "required"
        assert projected["materialization_ready"] is lane["materialization_ready"]
        assert tuple(
            (
                row["parameter"],
                row["kind"],
                tuple(row["consumers"]),
                row["requirement_digest"],
            )
            for row in projected["execution_requirements"]
        ) == tuple(
            (
                row.parameter,
                row.kind.value,
                row.consumers,
                row.requirement_digest,
            )
            for row in requirements
        )
