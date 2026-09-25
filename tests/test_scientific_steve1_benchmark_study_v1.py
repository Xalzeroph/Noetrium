from __future__ import annotations

from research.benchmarks.steve1_paper_prompts import (
    STEVE1_ALL_SPLIT,
    STEVE1_PAPER_PROMPT_NAMES,
    STEVE1_PAPER_PROMPTS_BENCHMARK_ID,
    STEVE1_PAPER_PROMPTS_BLOB_SHA,
    STEVE1_RELEASED_CELL_COUNT,
    STEVE1_TEXT_SPLIT,
    STEVE1_VISUAL_SPLIT,
    build_steve1_paper_prompt_cut,
)
from research.reproductions.steve1_minecraft import (
    STEVE1_METHOD_PROGRAM,
    build_steve1_neurips2023_prompt_benchmark,
    build_steve1_neurips2023_prompt_study,
    steve1_neurips2023_prompt_trial_protocol,
)


def test_steve1_released_prompt_cut_freezes_11_prompts_x_2_modalities() -> None:
    benchmark = build_steve1_paper_prompt_cut()
    assert benchmark.benchmark_id == STEVE1_PAPER_PROMPTS_BENCHMARK_ID
    assert STEVE1_PAPER_PROMPTS_BLOB_SHA == (
        "74f7522f9030a511e1f5c35c075adbe8f399047c"
    )
    assert STEVE1_PAPER_PROMPT_NAMES == (
        "dig",
        "dirt",
        "sky",
        "leaves",
        "wood",
        "seeds",
        "flower",
        "explore",
        "swim",
        "underwater",
        "inventory",
    )
    assert len(benchmark.selected_tasks(STEVE1_ALL_SPLIT)) == (
        STEVE1_RELEASED_CELL_COUNT
    ) == 22
    assert len(benchmark.selected_tasks(STEVE1_TEXT_SPLIT)) == 11
    assert len(benchmark.selected_tasks(STEVE1_VISUAL_SPLIT)) == 11
    assert {
        task.family for task in benchmark.selected_tasks(STEVE1_ALL_SPLIT)
    } == {"steve1_text_prompt", "steve1_visual_prompt"}


def test_steve1_study_binds_method_and_released_programmatic_metrics() -> None:
    benchmark = build_steve1_neurips2023_prompt_benchmark()
    protocol = steve1_neurips2023_prompt_trial_protocol(benchmark)
    study = build_steve1_neurips2023_prompt_study(benchmark)

    assert study.benchmark.cut_digest == benchmark.cut_digest
    assert study.benchmark_split_id == STEVE1_ALL_SPLIT
    assert (
        study.trial_protocol_identity.configuration_digest
        == protocol.configuration_digest
    )
    assert STEVE1_METHOD_PROGRAM.program_digest
    measurement_ids = {
        row.measurement_id
        for row in study.measurement_protocol.definitions
    }
    assert measurement_ids == {
        "max_log_inventory_count",
        "max_dirt_inventory_count",
        "max_seed_inventory_count",
        "max_travel_distance_blocks",
        "episode_steps",
    }
