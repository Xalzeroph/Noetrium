import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.benchmarks.mle_bench import (
    MLE_BENCH_FULL75_COMPETITIONS,
    MLE_BENCH_FULL75_SPLIT,
    MLE_BENCH_HIGH_COMPETITIONS,
    MLE_BENCH_HIGH_SPLIT,
    MLE_BENCH_LOW_COMPETITIONS,
    MLE_BENCH_LOW_SPLIT,
    MLE_BENCH_MEDIUM_COMPETITIONS,
    MLE_BENCH_MEDIUM_SPLIT,
    MleBenchCompetitionRecord,
    build_mle_bench_task_set,
)
from research.reproductions.mars_automated_ai_research import MARS_ARTIFACT_FIDELITY


def _benchmark():
    return build_mle_bench_task_set(
        tuple(
            MleBenchCompetitionRecord(
                competition_id=competition_id,
                content_digest=canonical_digest({"mle-bench": competition_id}),
            )
            for competition_id in MLE_BENCH_FULL75_COMPETITIONS
        ),
        source_digest=canonical_digest({"mle-bench-source": "1d391b01"}),
    )


def test_mle_bench_cut_freezes_full_and_complexity_splits() -> None:
    benchmark = _benchmark()
    assert len(benchmark.selected_tasks(MLE_BENCH_FULL75_SPLIT)) == 75
    assert len(benchmark.selected_tasks(MLE_BENCH_LOW_SPLIT)) == len(MLE_BENCH_LOW_COMPETITIONS) == 22
    assert len(benchmark.selected_tasks(MLE_BENCH_MEDIUM_SPLIT)) == len(MLE_BENCH_MEDIUM_COMPETITIONS) == 38
    assert len(benchmark.selected_tasks(MLE_BENCH_HIGH_SPLIT)) == len(MLE_BENCH_HIGH_COMPETITIONS) == 15


def test_mars_artifact_lane_never_claims_executable_method_source() -> None:
    fidelity = MARS_ARTIFACT_FIDELITY
    assert fidelity.source.kind.value == "official_artifact"
    assert fidelity.executable_mars_agent_source_available is False
    assert fidelity.run_count == 3
    assert fidelity.task_count_per_run == 75
    assert fidelity.valid_submission_counts == (74, 74, 74)


def test_mars_official_grading_reports_reconstruct_paper_leaderboard_statistics() -> None:
    fidelity = MARS_ARTIFACT_FIDELITY
    low_mean, low_sem = fidelity.low_medal_mean_sem
    medium_mean, medium_sem = fidelity.medium_medal_mean_sem
    high_mean, high_sem = fidelity.high_medal_mean_sem
    all_mean, all_sem = fidelity.all_medal_mean_sem

    assert low_mean == pytest.approx(74.24242424242425)
    assert low_sem == pytest.approx(1.515151515151511)
    assert medium_mean == pytest.approx(52.63157894736842)
    assert medium_sem == pytest.approx(3.0386856273138223)
    assert high_mean == pytest.approx(37.77777777777778)
    assert high_sem == pytest.approx(2.2222222222222237)
    assert all_mean == pytest.approx(56.0)
    assert all_sem == pytest.approx(1.5396007178390008)
