from __future__ import annotations
from noetrium_platform.research.experimentation.lifecycle.study.api import benchmark_selected_tasks
from research.benchmarks.voyager_minecraft import (
    VOYAGER_MINECRAFT_BENCHMARK_ID,
    VOYAGER_MINECRAFT_LIFELONG_SPLIT,
    VOYAGER_MINECRAFT_TRIAL_COUNT,
    build_voyager_minecraft_lifelong_cut,
)


def build_voyager_tmlr2024_benchmark():
    task_set = build_voyager_minecraft_lifelong_cut()
    if task_set.unit_id != VOYAGER_MINECRAFT_BENCHMARK_ID:
        raise ValueError("Voyager benchmark authority drifted")
    selected = benchmark_selected_tasks(task_set, VOYAGER_MINECRAFT_LIFELONG_SPLIT)
    if len(selected) != VOYAGER_MINECRAFT_TRIAL_COUNT:
        raise ValueError("Voyager TMLR protocol requires three trials")
    return task_set


__all__ = ["build_voyager_tmlr2024_benchmark"]
