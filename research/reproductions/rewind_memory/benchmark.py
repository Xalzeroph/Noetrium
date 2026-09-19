from __future__ import annotations

from noetrium_platform.research.experimentation.study.api import BenchmarkTaskSet
from research.benchmarks.moviechat_1k import (
    MOVIECHAT_1K_BENCHMARK_ID,
    MOVIECHAT_1K_TEST_SPLIT,
    MovieChatVideoRecord,
    bind_moviechat_1k_test_cut,
)


def build_rewind_cvpr2025_moviechat_test_cut(
    records: tuple[MovieChatVideoRecord, ...],
    *,
    dataset_content_sha256: str,
) -> BenchmarkTaskSet:
    resolution = bind_moviechat_1k_test_cut(
        records,
        dataset_content_sha256=dataset_content_sha256,
    )
    task_set = resolution.task_set
    if task_set.benchmark_id != MOVIECHAT_1K_BENCHMARK_ID:
        raise ValueError("ReWind MovieChat benchmark authority drifted")
    if len(task_set.selected_tasks(MOVIECHAT_1K_TEST_SPLIT)) != 1000:
        raise ValueError(
            "ReWind MovieChat-1K test cut must contain 1000 videos"
        )
    return task_set


__all__ = ["build_rewind_cvpr2025_moviechat_test_cut"]
