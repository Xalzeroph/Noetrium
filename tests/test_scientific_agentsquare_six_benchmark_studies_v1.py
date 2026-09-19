from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    TaskDefinition,
    TaskSetSplit,
)
from research.reproductions.agentsquare.reported import (
    AGENTSQUARE_BENCHMARK_PROFILES,
    AGENTSQUARE_BENCHMARK_PROFILE_BY_ID,
    AgentSquareTreatment,
)
from research.reproductions.agentsquare.study import (
    build_agentsquare_ablation_matrix,
    build_agentsquare_evaluation_study,
)


def _benchmark(profile) -> BenchmarkTaskSet:
    tasks = tuple(
        TaskDefinition(
            task_id=f"{profile.key}:paper-eval:{index:03d}",
            revision_id=profile.revision_id,
            family=profile.key,
            schema_id=f"{profile.key}.test-task.v1",
            content_digest=canonical_digest(
                {
                    "benchmark": profile.key,
                    "index": index,
                }
            ),
        )
        for index in range(profile.expected_evaluation_task_count)
    )
    return BenchmarkTaskSet(
        benchmark_id=profile.benchmark_id,
        revision_id=profile.revision_id,
        source_digest=canonical_digest(
            {"benchmark": profile.key, "source": "paper-eval"}
        ),
        task_schema_id=f"{profile.key}.test-task.v1",
        tasks=tasks,
        splits=(
            TaskSetSplit(
                profile.evaluation_split_id,
                tuple(row.task_id for row in tasks),
            ),
        ),
        selection_policy_digest=canonical_digest(
            {"benchmark": profile.key, "selection": "complete"}
        ),
    )


def test_agentsquare_freezes_six_benchmark_paper_targets() -> None:
    assert tuple(row.key for row in AGENTSQUARE_BENCHMARK_PROFILES) == (
        "webshop",
        "alfworld",
        "scienceworld",
        "m3tool",
        "travelplanner",
        "pddl",
    )
    assert tuple(
        row.expected_evaluation_task_count
        for row in AGENTSQUARE_BENCHMARK_PROFILES
    ) == (500, 134, 90, 82, 180, 60)
    assert tuple(
        row.gpt4o_scores.full for row in AGENTSQUARE_BENCHMARK_PROFILES
    ) == (0.607, 0.695, 0.781, 0.524, 0.583, 0.669)
    assert tuple(
        row.gpt4o_scores.without_module_evolution
        for row in AGENTSQUARE_BENCHMARK_PROFILES
    ) == (0.564, 0.649, 0.736, 0.502, 0.577, 0.614)
    assert tuple(
        row.gpt4o_scores.without_module_recombination
        for row in AGENTSQUARE_BENCHMARK_PROFILES
    ) == (0.560, 0.616, 0.710, 0.481, 0.280, 0.669)


def test_agentsquare_freezes_search_economics_separately_from_results() -> None:
    assert tuple(
        row.gpt4o_search.iterations_until_termination
        for row in AGENTSQUARE_BENCHMARK_PROFILES
    ) == (18, 15, 9, 18, 8, 12)
    assert tuple(
        row.gpt4o_search.average_cost_per_iteration_usd
        for row in AGENTSQUARE_BENCHMARK_PROFILES
    ) == (10.51, 13.96, 42.14, 26.03, 29.75, 26.94)
    assert all(
        row.gpt4o_search.reported_total_search_cost_usd > 0
        for row in AGENTSQUARE_BENCHMARK_PROFILES
    )


@pytest.mark.parametrize("profile", AGENTSQUARE_BENCHMARK_PROFILES)
@pytest.mark.parametrize("treatment", tuple(AgentSquareTreatment))
def test_agentsquare_builds_each_paper_ablation_study(
    profile,
    treatment,
) -> None:
    study = build_agentsquare_evaluation_study(
        _benchmark(profile),
        treatment=treatment,
        max_parallel_assignments=32,
    )

    assert study.benchmark.benchmark_id == profile.benchmark_id
    assert study.benchmark_split_id == profile.evaluation_split_id
    assert study.trial_protocol_identity.protocol_id == (
        f"agentsquare.iclr2025.{profile.key}.{treatment.value}.gpt4o.v1"
    )
    measurements = {
        row.measurement_id
        for row in study.measurement_protocol.definitions
    }
    assert profile.primary_measurement_id in measurements
    assert {
        "api_cost_usd",
        "model_call_count",
        "prompt_token_count",
        "completion_token_count",
    } <= measurements
    assert study.execution_policy.concurrency_policy.parallel_assignments is True
    assert (
        study.execution_policy.concurrency_policy.max_parallel_assignments
        == 32
    )


def test_agentsquare_ablation_matrix_contains_exactly_eighteen_studies() -> None:
    benchmarks = {
        profile.benchmark_id: _benchmark(profile)
        for profile in AGENTSQUARE_BENCHMARK_PROFILES
    }

    studies = build_agentsquare_ablation_matrix(
        benchmarks,
        max_parallel_assignments=8,
    )

    assert len(studies) == 18
    assert len({row.study_id for row in studies}) == 18
    assert {
        row.benchmark.benchmark_id for row in studies
    } == set(AGENTSQUARE_BENCHMARK_PROFILE_BY_ID)


def test_agentsquare_study_rejects_partial_benchmark_cut() -> None:
    profile = AGENTSQUARE_BENCHMARK_PROFILES[0]
    benchmark = _benchmark(profile)
    partial_tasks = benchmark.selected_tasks(profile.evaluation_split_id)[:-1]
    partial = BenchmarkTaskSet(
        benchmark_id=profile.benchmark_id,
        revision_id=profile.revision_id,
        source_digest=benchmark.source_digest,
        task_schema_id=benchmark.task_schema_id,
        tasks=partial_tasks,
        splits=(
            TaskSetSplit(
                profile.evaluation_split_id,
                tuple(row.task_id for row in partial_tasks),
            ),
        ),
        selection_policy_digest=benchmark.selection_policy_digest,
    )

    with pytest.raises(
        ValueError,
        match="task cardinality",
    ):
        build_agentsquare_evaluation_study(partial)
