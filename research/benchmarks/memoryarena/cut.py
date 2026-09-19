from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkSourceKind,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskDefinition,
    TaskPackageSpec,
    TaskSetSplit,
)

MEMORYARENA_BENCHMARK_ID = "memoryarena"
MEMORYARENA_CODE_REPOSITORY = "https://github.com/ZexueHe/MemoryArena"
MEMORYARENA_CODE_COMMIT = "6cd9de14b71915e39ac742a20dc33785e14b6aab"
MEMORYARENA_DATASET_LOCATOR = "https://huggingface.co/datasets/ZexueHe/memoryarena"
MEMORYARENA_TASK_SCHEMA_ID = "memoryarena.interdependent-multisession-task.v1"

MEMORYARENA_FAMILIES = (
    "formal_reasoning_math",
    "formal_reasoning_phys",
    "group_travel_planner",
    "web_search",
    "web_shopping",
)


@dataclass(frozen=True, slots=True, order=True)
class MemoryArenaTaskRecord:
    """One immutable top-level MemoryArena task from a pinned dataset cut."""

    task_id: str
    family: str
    split_id: str
    content_digest: str

    def __post_init__(self) -> None:
        if type(self.task_id) is not str or not self.task_id.strip():
            raise ValueError("MemoryArena task_id must be non-empty")
        if self.family not in MEMORYARENA_FAMILIES:
            raise ValueError(f"unsupported MemoryArena task family: {self.family!r}")
        if type(self.split_id) is not str or not self.split_id.strip():
            raise ValueError("MemoryArena split_id must be non-empty")
        require_sha256(self.content_digest, "MemoryArena task content_digest")


def memoryarena_revision(dataset_revision: str) -> str:
    if type(dataset_revision) is not str or not dataset_revision.strip():
        raise ValueError("MemoryArena dataset_revision must be non-empty")
    return f"memoryarena@{MEMORYARENA_CODE_COMMIT}:dataset@{dataset_revision.strip()}"


def build_memoryarena_source(
    *,
    dataset_revision: str,
    dataset_content_sha256: str,
) -> BenchmarkSourceSpec:
    """Freeze the external dataset/code identity before task materialization."""

    require_sha256(dataset_content_sha256, "MemoryArena dataset_content_sha256")
    revision = memoryarena_revision(dataset_revision)
    return BenchmarkSourceSpec(
        source_id=MEMORYARENA_BENCHMARK_ID,
        kind=BenchmarkSourceKind.HUGGINGFACE,
        revision_id=revision,
        locator=MEMORYARENA_DATASET_LOCATOR,
        content_digest=dataset_content_sha256,
        license=None,
        metadata={
            "code_repository": MEMORYARENA_CODE_REPOSITORY,
            "code_commit": MEMORYARENA_CODE_COMMIT,
            "task_semantics": "interdependent_multi_session",
        },
    )


def _task(record: MemoryArenaTaskRecord, revision: str) -> TaskDefinition:
    package = TaskPackageSpec(
        package_schema_id=f"memoryarena.{record.family}.package.v1",
        instruction_digest=record.content_digest,
        environment_requirement_id=f"benchmark.memoryarena.{record.family}.environment",
        verifier_requirement_id=f"benchmark.memoryarena.{record.family}.verifier",
    )
    return TaskDefinition(
        task_id=record.task_id,
        revision_id=revision,
        family=record.family,
        schema_id=MEMORYARENA_TASK_SCHEMA_ID,
        content_digest=record.content_digest,
        package=package,
    )


def build_memoryarena_task_set(
    records: tuple[MemoryArenaTaskRecord, ...],
    *,
    dataset_revision: str,
    dataset_content_sha256: str,
) -> BenchmarkTaskSet:
    """Adapt pinned MemoryArena dataset records into the generic Study benchmark ABI.

    The adapter owns only benchmark identity/task/split facts. Environment
    lifecycle, memory method behavior, model invocation and result authority
    remain outside the benchmark package.
    """

    if type(records) is not tuple or not records:
        raise ValueError("MemoryArena task records must be a non-empty tuple")
    if any(type(row) is not MemoryArenaTaskRecord for row in records):
        raise TypeError("MemoryArena records must contain MemoryArenaTaskRecord")
    require_sha256(dataset_content_sha256, "MemoryArena dataset_content_sha256")

    ordered = tuple(sorted(records, key=lambda row: row.task_id))
    task_ids = tuple(row.task_id for row in ordered)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("MemoryArena task ids must be unique")

    revision = memoryarena_revision(dataset_revision)
    tasks = tuple(_task(row, revision) for row in ordered)

    split_names = tuple(sorted({row.split_id for row in ordered}))
    splits = tuple(
        TaskSetSplit(
            split_id,
            tuple(row.task_id for row in ordered if row.split_id == split_id),
        )
        for split_id in split_names
    )
    selection_policy_digest = canonical_digest(
        {
            "benchmark_id": MEMORYARENA_BENCHMARK_ID,
            "code_commit": MEMORYARENA_CODE_COMMIT,
            "dataset_revision": dataset_revision,
            "families": MEMORYARENA_FAMILIES,
            "splits": tuple(
                (row.split_id, row.task_ids)
                for row in splits
            ),
        }
    )
    return BenchmarkTaskSet(
        benchmark_id=MEMORYARENA_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id=MEMORYARENA_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=splits,
        selection_policy_digest=selection_policy_digest,
    )


__all__ = [
    "MEMORYARENA_BENCHMARK_ID",
    "MEMORYARENA_CODE_COMMIT",
    "MEMORYARENA_CODE_REPOSITORY",
    "MEMORYARENA_DATASET_LOCATOR",
    "MEMORYARENA_FAMILIES",
    "MEMORYARENA_TASK_SCHEMA_ID",
    "MemoryArenaTaskRecord",
    "build_memoryarena_source",
    "build_memoryarena_task_set",
    "memoryarena_revision",
]
