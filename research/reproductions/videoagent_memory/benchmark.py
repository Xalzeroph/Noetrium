from __future__ import annotations

from noetrium_platform.research.experimentation.study.api import BenchmarkTaskSet
from research.benchmarks.egoschema import (
    EGOSCHEMA_BENCHMARK_ID,
    EGOSCHEMA_FULL_COUNT,
    EGOSCHEMA_FULL_SPLIT,
    EGOSCHEMA_PUBLIC_COUNT,
    EGOSCHEMA_PUBLIC_SPLIT,
    EgoSchemaTaskRecord,
    bind_egoschema_full_5031,
    bind_egoschema_public_500,
)


def build_videoagent_egoschema_public_cut(
    records: tuple[EgoSchemaTaskRecord, ...],
    *,
    questions_content_sha256: str,
    public_answers_content_sha256: str,
) -> BenchmarkTaskSet:
    task_set = bind_egoschema_public_500(
        records,
        questions_content_sha256=questions_content_sha256,
        public_answers_content_sha256=public_answers_content_sha256,
    ).task_set
    if task_set.benchmark_id != EGOSCHEMA_BENCHMARK_ID:
        raise ValueError("VideoAgent EgoSchema benchmark authority drifted")
    if len(task_set.selected_tasks(EGOSCHEMA_PUBLIC_SPLIT)) != (
        EGOSCHEMA_PUBLIC_COUNT
    ):
        raise ValueError("VideoAgent public EgoSchema cut must contain 500 tasks")
    return task_set


def build_videoagent_egoschema_full_cut(
    records: tuple[EgoSchemaTaskRecord, ...],
    *,
    questions_content_sha256: str,
    public_answers_content_sha256: str,
) -> BenchmarkTaskSet:
    task_set = bind_egoschema_full_5031(
        records,
        questions_content_sha256=questions_content_sha256,
        public_answers_content_sha256=public_answers_content_sha256,
    ).task_set
    if len(task_set.selected_tasks(EGOSCHEMA_FULL_SPLIT)) != (
        EGOSCHEMA_FULL_COUNT
    ):
        raise ValueError("VideoAgent full EgoSchema cut must contain 5031 tasks")
    return task_set


__all__ = [
    "build_videoagent_egoschema_full_cut",
    "build_videoagent_egoschema_public_cut",
]
