from __future__ import annotations

from noetrium_platform.research.experimentation.study.api import BenchmarkTaskSet
from research.benchmarks.egolifeqa import (
    EGOLIFEQA_BENCHMARK_ID,
    EgoLifeQATaskRecord,
    bind_egolifeqa_subject_cut,
)


def build_worldmm_egolifeqa_subject_cut(
    records: tuple[EgoLifeQATaskRecord, ...],
    *,
    question_file_content_sha256: str,
    subject_id: str = "A1_JAKE",
) -> BenchmarkTaskSet:
    task_set = bind_egolifeqa_subject_cut(
        records,
        question_file_content_sha256=question_file_content_sha256,
        subject_id=subject_id,
    ).task_set
    if task_set.benchmark_id != EGOLIFEQA_BENCHMARK_ID:
        raise ValueError("WorldMM EgoLifeQA benchmark authority drifted")
    split_id = f"subject:{subject_id}"
    selected = task_set.selected_tasks(split_id)
    if not selected:
        raise ValueError("WorldMM EgoLifeQA subject cut is empty")
    return task_set


__all__ = ["build_worldmm_egolifeqa_subject_cut"]
