from __future__ import annotations

from noetrium import api

from collections import defaultdict
from dataclasses import dataclass

    api.BenchmarkSourceKind, api.BenchmarkSourceSpec, api.BenchmarkTaskSet,
    api.TaskDefinition, api.TaskSetSplit,
)

BENCHMARK_ID = "envqa"
OFFICIAL_REPOSITORY = "https://github.com/maybelu9/env-qa"
SOURCE_COMMIT = "3e6018fe2eaa941529f955c64c8116ba42f986c4"
REVISION = f"envqa@{SOURCE_COMMIT}"
TASK_SCHEMA_ID = "envqa.question.v1"


@dataclass(frozen=True, slots=True)
class TaskRecord:
    split_id: str
    task_key: str
    content_digest: str
    def __post_init__(self) -> None:
        if type(self.split_id) is not str or not self.split_id.strip():
            raise ValueError("Env-QA split_id must be text")
        if type(self.task_key) is not str or not self.task_key.strip():
            raise ValueError("Env-QA task_key must be text")
        api.require_sha256(self.content_digest, "Env-QA task content_digest")
    @property
    def task_id(self) -> str:
        return f"envqa:{self.split_id}:{self.task_key}"


def build_source_spec(*, content_digest: str) -> api.BenchmarkSourceSpec:
    api.require_sha256(content_digest, "Env-QA source content_digest")
    return api.BenchmarkSourceSpec(
        source_id=BENCHMARK_ID,
        kind=api.BenchmarkSourceKind.GIT,
        revision_id=REVISION,
        locator=OFFICIAL_REPOSITORY,
        content_digest=content_digest,
        metadata={"repository": OFFICIAL_REPOSITORY, "commit": SOURCE_COMMIT},
    )


def build_task_set(records: tuple[TaskRecord, ...], *, source_digest: str) -> api.BenchmarkTaskSet:
    if type(records) is not tuple or not records or any(type(row) is not TaskRecord for row in records):
        raise TypeError("Env-QA records must be a non-empty TaskRecord tuple")
    api.require_sha256(source_digest, "Env-QA source_digest")
    task_ids = [row.task_id for row in records]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Env-QA task identities must be unique")
    tasks = tuple(sorted((
        api.TaskDefinition(
            task_id=row.task_id,
            revision_id=REVISION,
            family="envqa",
            schema_id=TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(f"split:{row.split_id}", f"source-commit:{SOURCE_COMMIT}"),
        )
        for row in records
    ), key=lambda row: row.task_id))
    splits: dict[str, list[str]] = defaultdict(list)
    for row in records:
        splits[row.split_id].append(row.task_id)
    split_rows = tuple(
        api.TaskSetSplit(split_id, tuple(sorted(ids)))
        for split_id, ids in sorted(splits.items())
    )
    return api.BenchmarkCutSpec(
        benchmark_id=BENCHMARK_ID,
        revision_id=REVISION,
        source_digest=source_digest,
        task_schema_id=TASK_SCHEMA_ID,
    ).build(
        tasks,
        splits=split_rows,
        selection_policy={
            "benchmark_id": BENCHMARK_ID,
            "revision": REVISION,
            "task_ids": tuple(row.task_id for row in tasks),
            "selection": "content_addressed_external_release",
        },
    )


__all__ = [
    "BENCHMARK_ID", "OFFICIAL_REPOSITORY", "SOURCE_COMMIT", "REVISION",
    "TASK_SCHEMA_ID", "TaskRecord", "build_source_spec", "build_task_set",
]
