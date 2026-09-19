from __future__ import annotations

from noetrium_platform.research.experimentation.study.api import BenchmarkTaskSet
from research.benchmarks.jarvis1_offline import (
    JARVIS1_ALL_SPLIT,
    JARVIS1_OFFLINE_BENCHMARK_ID,
    JARVIS1_TASK_COUNT,
    build_jarvis1_offline_cut,
)


def build_jarvis1_tpami2025_offline_benchmark() -> BenchmarkTaskSet:
    task_set = build_jarvis1_offline_cut()
    if task_set.benchmark_id != JARVIS1_OFFLINE_BENCHMARK_ID:
        raise ValueError("JARVIS-1 benchmark authority drifted")
    if len(task_set.selected_tasks(JARVIS1_ALL_SPLIT)) != JARVIS1_TASK_COUNT:
        raise ValueError("JARVIS-1 official offline cut must contain 185 rows")
    return task_set


__all__ = ["build_jarvis1_tpami2025_offline_benchmark"]
