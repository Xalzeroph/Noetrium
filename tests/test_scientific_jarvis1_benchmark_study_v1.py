from __future__ import annotations

from research.benchmarks.jarvis1_offline import (
    JARVIS1_ALL_SPLIT,
    JARVIS1_GROUP_COUNTS,
    JARVIS1_OFFLINE_BENCHMARK_ID,
    JARVIS1_TASK_COUNT,
    JARVIS1_TASK_IDENTITIES,
    JARVIS1_TASKS_BLOB_SHA,
    build_jarvis1_offline_cut,
)
from research.reproductions.jarvis1_minecraft import (
    JARVIS1_MEMORY_PROGRAM,
    JARVIS1_PUBLIC_MAX_ENVIRONMENT_STEP,
    build_jarvis1_tpami2025_offline_benchmark,
    build_jarvis1_tpami2025_public_offline_study,
    jarvis1_tpami2025_public_offline_trial_protocol,
)


def test_jarvis1_official_offline_cut_preserves_185_source_rows() -> None:
    benchmark = build_jarvis1_offline_cut()
    assert benchmark.benchmark_id == JARVIS1_OFFLINE_BENCHMARK_ID
    assert JARVIS1_TASKS_BLOB_SHA == (
        "8cc441f240cf080a957c9d2987fc4f0d062d3309"
    )
    assert len(benchmark.selected_tasks(JARVIS1_ALL_SPLIT)) == (
        JARVIS1_TASK_COUNT
    ) == 185
    assert len(JARVIS1_GROUP_COUNTS) == 16
    assert sum(count for _, count in JARVIS1_GROUP_COUNTS) == 185
    assert sum(
        1 for _, _, task in JARVIS1_TASK_IDENTITIES
        if task == "orange_bed"
    ) == 2
    assert len({
        task.task_id
        for task in benchmark.selected_tasks(JARVIS1_ALL_SPLIT)
    }) == 185


def test_jarvis1_public_study_binds_memory_and_offline_evaluator() -> None:
    benchmark = build_jarvis1_tpami2025_offline_benchmark()
    protocol = jarvis1_tpami2025_public_offline_trial_protocol(benchmark)
    study = build_jarvis1_tpami2025_public_offline_study(benchmark)

    assert study.benchmark.cut_digest == benchmark.cut_digest
    assert study.benchmark_split_id == JARVIS1_ALL_SPLIT
    assert (
        study.trial_protocol_identity.configuration_digest
        == protocol.configuration_digest
    )
    assert JARVIS1_MEMORY_PROGRAM.program_digest
    assert JARVIS1_PUBLIC_MAX_ENVIRONMENT_STEP == 11999
    measurement_ids = {
        row.measurement_id
        for row in study.measurement_protocol.definitions
    }
    assert measurement_ids == {
        "fixed_memory_hit",
        "retrieved_plan_step_count",
        "offline_task_success",
        "offline_environment_steps",
    }
