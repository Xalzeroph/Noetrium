from __future__ import annotations

import pytest

from noetrium import api
from research.benchmarks.alfworld import (
    ALFWORLD_BENCHMARK_ID,
    ALFWORLD_PAPER_EVAL_REVISION,
    ALFWORLD_PAPER_EVAL_SPLIT,
    ALFWORLD_QLASS_DEV_REVISION,
    ALFWORLD_QLASS_DEV_SPLIT,
)
from research.reproductions.agentsquare.definition import REPRODUCTION as AGENTSQUARE
from research.reproductions.qlass_alfworld.definition import REPRODUCTION as QLASS
from research.reproductions.react_alfworld.definition import REPRODUCTION as REACT
from research.reproductions.reflexion_alfworld.definition import REPRODUCTION as REFLEXION
from research.reproductions.research_os import resolve_study_factory_bindings


def test_public_api_exposes_exact_benchmark_cut_authoring() -> None:
    assert api.BenchmarkCutRequirement.__name__ == "BenchmarkCutRequirement"
    assert callable(api.requires_benchmark_cut)
    assert callable(api.benchmark_cut_requirements)


def test_benchmark_cut_requirement_is_canonical_and_checks_revision_split() -> None:
    requirement = api.BenchmarkCutRequirement(
        "fixture",
        "revision-2",
        ("test", "dev"),
    )
    assert requirement.required_split_ids == ("dev", "test")
    assert len(requirement.requirement_digest) == 64

    source_digest = api.canonical_digest({"fixture": "revision-2"})
    tasks = (
        api.TaskDefinition(
            "dev-task",
            "revision-2",
            "fixture",
            "fixture.task.v1",
            api.canonical_digest({"task": "dev"}),
        ),
        api.TaskDefinition(
            "test-task",
            "revision-2",
            "fixture",
            "fixture.task.v1",
            api.canonical_digest({"task": "test"}),
        ),
    )
    benchmark = api.BenchmarkTaskSet(
        benchmark_id="fixture",
        revision_id="revision-2",
        source_digest=source_digest,
        task_schema_id="fixture.task.v1",
        tasks=tasks,
        splits=(
            api.TaskSetSplit("dev", ("dev-task",)),
            api.TaskSetSplit("test", ("test-task",)),
        ),
    )
    assert requirement.matches(benchmark)
    assert not api.BenchmarkCutRequirement("fixture", "revision-1").matches(
        benchmark
    )


def test_benchmark_cut_decorator_rejects_two_revisions_for_same_benchmark() -> None:
    @api.requires_benchmark_cut("fixture", "r1")
    def factory(benchmark):
        return benchmark

    with pytest.raises(ValueError, match="multiple exact cuts"):
        api.requires_benchmark_cut("fixture", "r2")(factory)


def test_alfworld_papers_expose_their_exact_cut_requirements() -> None:
    react = resolve_study_factory_bindings(REACT)[0].benchmark_requirement(
        ALFWORLD_BENCHMARK_ID
    )
    reflexion = resolve_study_factory_bindings(REFLEXION)[0].benchmark_requirement(
        ALFWORLD_BENCHMARK_ID
    )
    qlass = resolve_study_factory_bindings(QLASS)[0].benchmark_requirement(
        ALFWORLD_BENCHMARK_ID
    )

    assert react is not None
    assert react.revision_id == ALFWORLD_PAPER_EVAL_REVISION
    assert react.required_split_ids == (ALFWORLD_PAPER_EVAL_SPLIT,)
    assert reflexion == react
    assert qlass is not None
    assert qlass.revision_id == ALFWORLD_QLASS_DEV_REVISION
    assert qlass.required_split_ids == (ALFWORLD_QLASS_DEV_SPLIT,)


def test_agentsquare_declares_all_six_published_benchmark_cuts() -> None:
    binding = resolve_study_factory_bindings(AGENTSQUARE)[0]
    assert len(binding.benchmark_requirements) == 6
    assert {row.benchmark_id for row in binding.benchmark_requirements} == set(
        AGENTSQUARE.catalog.benchmark_ids
    )
