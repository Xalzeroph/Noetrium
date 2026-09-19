from __future__ import annotations

from noetrium_platform.research.experimentation.study.api import BenchmarkTaskSet
from research.benchmarks.voyager_minecraft import (
    VOYAGER_MINECRAFT_BENCHMARK_ID,
    VOYAGER_MINECRAFT_LIFELONG_SPLIT,
    VOYAGER_MINECRAFT_TRIAL_COUNT,
    build_voyager_minecraft_lifelong_cut,
)


def build_voyager_tmlr2024_benchmark() -> BenchmarkTaskSet:
    task_set = build_voyager_minecraft_lifelong_cut()
    if task_set.benchmark_id != VOYAGER_MINECRAFT_BENCHMARK_ID:
        raise ValueError("Voyager benchmark authority drifted")
    selected = task_set.selected_tasks(VOYAGER_MINECRAFT_LIFELONG_SPLIT)
    if len(selected) != VOYAGER_MINECRAFT_TRIAL_COUNT:
        raise ValueError("Voyager TMLR protocol requires three trials")
    return task_set


__all__ = ["build_voyager_tmlr2024_benchmark"]
