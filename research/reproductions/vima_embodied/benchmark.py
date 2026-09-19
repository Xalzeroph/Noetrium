from __future__ import annotations

from noetrium_platform.research.experimentation.study.api import BenchmarkTaskSet
from research.benchmarks.vima_bench import (
    VIMA_BENCHMARK_ID,
    VIMA_PARTITION_TASKS,
    build_vima_bench_camera_ready_cut,
)


def build_vima_icml2023_benchmark() -> BenchmarkTaskSet:
    benchmark = build_vima_bench_camera_ready_cut()
    if benchmark.benchmark_id != VIMA_BENCHMARK_ID:
        raise ValueError("VIMA-Bench authority drifted")
    if len(benchmark.tasks) != 43:
        raise ValueError("VIMA camera-ready cut must contain 43 task-partition cells")
    for partition, task_names in VIMA_PARTITION_TASKS.items():
        selected = benchmark.selected_tasks(partition)
        if len(selected) != len(task_names):
            raise ValueError(
                f"VIMA partition size drifted: {partition}"
            )
    return benchmark


__all__ = ["build_vima_icml2023_benchmark"]
