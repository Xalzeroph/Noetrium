from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    TaskDefinition,
    TaskSetSplit,
)

MATH500_BENCHMARK_ID = "math500"
MATH500_LITS_SOURCE_COMMIT = "4f522bb7bf5d5bfd68c42649efe44c566dfa039c"
MATH500_LITS_REVISION = f"lits@{MATH500_LITS_SOURCE_COMMIT}:xinzhel/math500-float:test"
MATH500_TEST_SPLIT = "test"
MATH500_EXPECTED_TASK_COUNT = 500
MATH500_TASK_SCHEMA_ID = "math500.problem.v1"
MATH500_SELECTION_POLICY_DIGEST = canonical_digest(
    {
        "benchmark_id": MATH500_BENCHMARK_ID,
        "revision_id": MATH500_LITS_REVISION,
        "dataset": "xinzhel/math500-float",
        "split": MATH500_TEST_SPLIT,
        "selection": "all_tasks_in_dataset_order",
        "expected_task_count": MATH500_EXPECTED_TASK_COUNT,
    }
)


@dataclass(frozen=True, slots=True)
class Math500TaskRecord:
    index: int
    content_digest: str
    level: str | None = None

    def __post_init__(self) -> None:
        if type(self.index) is not int or not 0 <= self.index < MATH500_EXPECTED_TASK_COUNT:
            raise ValueError("MATH500 task index must be in [0, 500)")
        require_sha256(self.content_digest, "MATH500 task content_digest")
        if self.level is not None and (type(self.level) is not str or not self.level.strip()):
            raise ValueError("MATH500 level must be non-empty when provided")

    @property
    def task_id(self) -> str:
        return f"math500:{self.index:03d}"


def build_math500_lits_task_set(
    records: tuple[Math500TaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    """Freeze the full xinzhel/math500-float test split used by LiTS."""

    if type(records) is not tuple or any(type(row) is not Math500TaskRecord for row in records):
        raise TypeError("MATH500 records must be a tuple of Math500TaskRecord")
    require_sha256(source_digest, "MATH500 source_digest")
    by_index = {row.index: row for row in records}
    expected = tuple(range(MATH500_EXPECTED_TASK_COUNT))
    if len(records) != MATH500_EXPECTED_TASK_COUNT or tuple(sorted(by_index)) != expected:
        raise ValueError("LiTS MATH500 cut requires exactly indices 0 through 499")

    ordered = tuple(by_index[index] for index in expected)
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=MATH500_LITS_REVISION,
            family="math500",
            schema_id=MATH500_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"dataset-index:{row.index}",
                f"level:{row.level}" if row.level is not None else "level:unspecified",
                f"lits-source-commit:{MATH500_LITS_SOURCE_COMMIT}",
            ),
        )
        for row in ordered
    )
    return BenchmarkTaskSet(
        benchmark_id=MATH500_BENCHMARK_ID,
        revision_id=MATH500_LITS_REVISION,
        source_digest=source_digest,
        task_schema_id=MATH500_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(TaskSetSplit(MATH500_TEST_SPLIT, tuple(row.task_id for row in ordered)),),
        selection_policy_digest=MATH500_SELECTION_POLICY_DIGEST,
    )


__all__ = [
    "MATH500_BENCHMARK_ID",
    "MATH500_EXPECTED_TASK_COUNT",
    "MATH500_LITS_REVISION",
    "MATH500_LITS_SOURCE_COMMIT",
    "MATH500_SELECTION_POLICY_DIGEST",
    "MATH500_TASK_SCHEMA_ID",
    "MATH500_TEST_SPLIT",
    "Math500TaskRecord",
    "build_math500_lits_task_set",
]
