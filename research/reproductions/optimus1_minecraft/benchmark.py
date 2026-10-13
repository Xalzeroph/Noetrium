from __future__ import annotations
from noetrium_platform.research.experimentation.lifecycle.study.api import benchmark_selected_tasks
from research.benchmarks.minecraft_long_horizon_67 import (
    MINECRAFT_LONG_HORIZON_67_ALL_SPLIT,
    MINECRAFT_LONG_HORIZON_67_BENCHMARK_ID,
    MINECRAFT_LONG_HORIZON_67_TASK_COUNT,
    build_minecraft_long_horizon_67_cut,
)


def build_optimus1_long_horizon_67_cut():
    task_set = build_minecraft_long_horizon_67_cut()
    if task_set.unit_id != MINECRAFT_LONG_HORIZON_67_BENCHMARK_ID:
        raise ValueError("optimus1 benchmark authority drifted")
    if len(benchmark_selected_tasks(task_set, MINECRAFT_LONG_HORIZON_67_ALL_SPLIT)) != (
        MINECRAFT_LONG_HORIZON_67_TASK_COUNT
    ):
        raise ValueError("optimus1 paper protocol requires 67 tasks")
    return task_set


__all__ = ["build_optimus1_long_horizon_67_cut"]
