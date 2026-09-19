from __future__ import annotations

from noetrium_platform.research.experimentation.study.api import BenchmarkTaskSet
from research.benchmarks.saycan_101 import (
    SAYCAN_ALL_SPLIT,
    SAYCAN_BENCHMARK_ID,
    SAYCAN_TASK_COUNT,
    SayCanTaskRecord,
    bind_saycan_v0,
    bind_saycan_v0_tsv,
)


def build_saycan_101_benchmark(
    records: tuple[SayCanTaskRecord, ...],
) -> BenchmarkTaskSet:
    benchmark = bind_saycan_v0(records).task_set
    if benchmark.benchmark_id != SAYCAN_BENCHMARK_ID:
        raise ValueError("SayCan benchmark authority drifted")
    if len(benchmark.selected_tasks(SAYCAN_ALL_SPLIT)) != SAYCAN_TASK_COUNT:
        raise ValueError("SayCan evaluation cut must contain 101 tasks")
    return benchmark


def build_saycan_101_benchmark_from_tsv(text: str) -> BenchmarkTaskSet:
    benchmark = bind_saycan_v0_tsv(text).task_set
    if len(benchmark.selected_tasks(SAYCAN_ALL_SPLIT)) != SAYCAN_TASK_COUNT:
        raise ValueError("SayCan evaluation TSV must contain 101 tasks")
    return benchmark


__all__ = [
    "build_saycan_101_benchmark",
    "build_saycan_101_benchmark_from_tsv",
]
