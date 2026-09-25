from __future__ import annotations

from research.benchmarks.voyager_minecraft import (
    VOYAGER_MINECRAFT_BENCHMARK_ID,
    VOYAGER_MINECRAFT_LIFELONG_SPLIT,
    VOYAGER_MINECRAFT_MAX_PROMPTING_ITERATIONS,
    VOYAGER_MINECRAFT_TRIAL_COUNT,
)
from research.reproductions.voyager_minecraft.benchmark import (
    build_voyager_tmlr2024_benchmark,
)
from research.reproductions.voyager_minecraft.study import (
    build_voyager_tmlr2024_study,
    voyager_tmlr2024_trial_protocol,
)


def test_voyager_benchmark_freezes_three_independent_160_iteration_trials() -> None:
    benchmark = build_voyager_tmlr2024_benchmark()
    assert benchmark.benchmark_id == VOYAGER_MINECRAFT_BENCHMARK_ID
    trials = benchmark.selected_tasks(VOYAGER_MINECRAFT_LIFELONG_SPLIT)
    assert len(trials) == VOYAGER_MINECRAFT_TRIAL_COUNT == 3
    assert all(
        "fresh-world:true" in task.lineage_refs
        and "world-seed:paper-unpublished" in task.lineage_refs
        and "max-prompting-iterations:160" in task.lineage_refs
        and "task-reset:reset-rejoin" in task.lineage_refs
        for task in trials
    )
    assert VOYAGER_MINECRAFT_MAX_PROMPTING_ITERATIONS == 160


def test_voyager_study_binds_method_memories_and_paper_metrics() -> None:
    benchmark = build_voyager_tmlr2024_benchmark()
    protocol = voyager_tmlr2024_trial_protocol(benchmark)
    definition = build_voyager_tmlr2024_study(benchmark)

    assert protocol.protocol_id == "voyager.tmlr2024.open-world-lifelong.v1"
    assert definition.benchmark_split_id == VOYAGER_MINECRAFT_LIFELONG_SPLIT
    assert (
        definition.trial_protocol_identity.configuration_digest
        == protocol.configuration_digest
    )
    assert len(
        benchmark.selected_tasks(definition.benchmark_split_id)
    ) == 3
    assert definition.repetitions == 1
    names = {
        row.measurement_id
        for row in definition.measurement_protocol.definitions
    }
    assert {
        "unique_item_count",
        "wooden_tool_unlock_iteration",
        "stone_tool_unlock_iteration",
        "iron_tool_unlock_iteration",
        "diamond_tool_unlock_iteration",
        "travel_distance_blocks",
        "learned_skill_count",
    }.issubset(names)
