from __future__ import annotations
from research.benchmarks.minecraft_long_horizon_67 import (
    MINECRAFT_LONG_HORIZON_67_ALL_SPLIT,
    MINECRAFT_LONG_HORIZON_67_BENCHMARK_ID,
    MINECRAFT_LONG_HORIZON_67_TASK_COUNT,
    build_minecraft_long_horizon_67_cut,
)


def build_optimus2_long_horizon_67_cut():
    task_set = build_minecraft_long_horizon_67_cut()
    if task_set.benchmark_id != MINECRAFT_LONG_HORIZON_67_BENCHMARK_ID:
        raise ValueError("optimus2 benchmark authority drifted")
    if len(task_set.selected_tasks(MINECRAFT_LONG_HORIZON_67_ALL_SPLIT)) != (
        MINECRAFT_LONG_HORIZON_67_TASK_COUNT
    ):
        raise ValueError("optimus2 paper protocol requires 67 tasks")
    return task_set


__all__ = ["build_optimus2_long_horizon_67_cut"]
