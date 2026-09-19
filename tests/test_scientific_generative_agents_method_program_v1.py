from __future__ import annotations

from research.benchmarks.generative_agents_smallville import (
    GENERATIVE_AGENTS_BENCHMARK_ID,
    build_generative_agents_smallville_cut,
)
from research.reproductions.generative_agents_memory.program import (
    build_generative_agents_method_program,
)
from research.reproductions.generative_agents_memory.study import (
    build_generative_agents_smallville_study,
)


def test_generative_agents_program_exposes_paper_component_ablations() -> None:
    full = build_generative_agents_method_program()
    no_reflection = build_generative_agents_method_program(
        enable_reflection=False,
    )
    no_planning = build_generative_agents_method_program(
        enable_planning=False,
    )
    assert full.program_digest != no_reflection.program_digest
    assert full.program_digest != no_planning.program_digest
    assert "believability_score" in full.metric_names


def test_generative_agents_smallville_cut_and_study_are_protocol_bound() -> None:
    benchmark = build_generative_agents_smallville_cut()
    assert benchmark.benchmark_id == GENERATIVE_AGENTS_BENCHMARK_ID
    assert len(benchmark.tasks) == 1
    study = build_generative_agents_smallville_study(benchmark)
    assert study.benchmark.benchmark_id == GENERATIVE_AGENTS_BENCHMARK_ID
    assert tuple(row.measurement_id for row in study.measurement_protocol.definitions) == (
        "believability_score",
        "reflection_count",
        "model_call_count",
    )
