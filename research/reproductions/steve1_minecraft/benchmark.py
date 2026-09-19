from __future__ import annotations

from noetrium_platform.research.experimentation.study.api import BenchmarkTaskSet
from research.benchmarks.steve1_paper_prompts import (
    STEVE1_ALL_SPLIT,
    STEVE1_PAPER_PROMPTS_BENCHMARK_ID,
    STEVE1_RELEASED_CELL_COUNT,
    build_steve1_paper_prompt_cut,
)


def build_steve1_neurips2023_prompt_benchmark() -> BenchmarkTaskSet:
    task_set = build_steve1_paper_prompt_cut()
    if task_set.benchmark_id != STEVE1_PAPER_PROMPTS_BENCHMARK_ID:
        raise ValueError("STEVE-1 benchmark authority drifted")
    if len(task_set.selected_tasks(STEVE1_ALL_SPLIT)) != (
        STEVE1_RELEASED_CELL_COUNT
    ):
        raise ValueError("STEVE-1 released prompt cell count drifted")
    return task_set


__all__ = ["build_steve1_neurips2023_prompt_benchmark"]
