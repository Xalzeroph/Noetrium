from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkSourceKind, BenchmarkSourceSpec, BenchmarkTaskSet,
    TaskDefinition, TaskSetSplit,
)

BENCHMARK_ID = "ego4d-vq3d"
OFFICIAL_REPOSITORY = "https://github.com/facebookresearch/Ego4d"
SOURCE_COMMIT = "4bd10ed40b4f8d8ad26344afc2c8526f7d1dedeb"
REVISION = f"ego4d-vq3d@{SOURCE_COMMIT}"
TASK_SCHEMA_ID = "ego4d-vq3d.query.v1"


@dataclass(frozen=True, slots=True)
class TaskRecord:
    split_id: str
    task_key: str
    content_digest: str
    def __post_init__(self) -> None:
        if type(self.split_id) is not str or not self.split_id.strip():
            raise ValueError("Ego4D VQ3D split_id must be text")
        if type(self.task_key) is not str or not self.task_key.strip():
            raise ValueError("Ego4D VQ3D task_key must be text")
        require_sha256(self.content_digest, "Ego4D VQ3D task content_digest")
    @property
    def task_id(self) -> str:
        return f"ego4d-vq3d:{self.split_id}:{self.task_key}"


def build_source_spec(*, content_digest: str) -> BenchmarkSourceSpec:
    require_sha256(content_digest, "Ego4D VQ3D source content_digest")
    return BenchmarkSourceSpec(
        source_id=BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=REVISION,
        locator=OFFICIAL_REPOSITORY,
        content_digest=content_digest,
        metadata={"repository": OFFICIAL_REPOSITORY, "commit": SOURCE_COMMIT},
    )


def build_task_set(records: tuple[TaskRecord, ...], *, source_digest: str) -> BenchmarkTaskSet:
    if type(records) is not tuple or not records or any(type(row) is not TaskRecord for row in records):
        raise TypeError("Ego4D VQ3D records must be a non-empty TaskRecord tuple")
    require_sha256(source_digest, "Ego4D VQ3D source_digest")
    task_ids = [row.task_id for row in records]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Ego4D VQ3D task identities must be unique")
    tasks = tuple(sorted((
        TaskDefinition(
            task_id=row.task_id,
            revision_id=REVISION,
            family="ego4d_vq3d",
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
        TaskSetSplit(split_id, tuple(sorted(ids)))
        for split_id, ids in sorted(splits.items())
    )
    return BenchmarkTaskSet(
        benchmark_id=BENCHMARK_ID,
        revision_id=REVISION,
        source_digest=source_digest,
        task_schema_id=TASK_SCHEMA_ID,
        tasks=tasks,
        splits=split_rows,
        selection_policy_digest=canonical_digest({
            "benchmark_id": BENCHMARK_ID,
            "revision": REVISION,
            "task_ids": tuple(row.task_id for row in tasks),
            "selection": "content_addressed_external_release",
        }),
    )


__all__ = [
    "BENCHMARK_ID", "OFFICIAL_REPOSITORY", "SOURCE_COMMIT", "REVISION",
    "TASK_SCHEMA_ID", "TaskRecord", "build_source_spec", "build_task_set",
]
