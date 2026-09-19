from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkSourceKind,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskDefinition,
    TaskSetSplit,
)

GATS_SYNTHETIC_BENCHMARK_ID = "gats-synthetic"
GATS_SOURCE_REPOSITORY = "https://github.com/MMWilliams/gats"
GATS_REPRO_SOURCE_COMMIT = "c8cb71cc23bc622e1711ec4bec274071a87940bc"
GATS_STRESS_SOURCE_PATH = "experiments/run_stress_test.py"
GATS_STRESS_SOURCE_BLOB_SHA1 = "174a6d5bdbb6ee85d3e0801be4b2a7c381569338"
GATS_STRESS_REVISION = f"gats@{GATS_REPRO_SOURCE_COMMIT}:stress-12x10"
GATS_STRESS_SPLIT = "stress_12x10"
GATS_STRESS_TASKS_PER_CATEGORY = 10
GATS_STRESS_CATEGORIES = (
    "trap_heavy",
    "deep_horizon",
    "high_branching",
    "deceptive",
    "resource_puzzle",
    "critical_choice",
    "memory_limit",
    "no_backtrack",
    "web_navigation",
    "coding_task",
    "very_long_horizon",
    "commitment_cascade",
)
GATS_STRESS_TASK_COUNT = len(GATS_STRESS_CATEGORIES) * GATS_STRESS_TASKS_PER_CATEGORY
GATS_STRESS_TASK_SCHEMA_ID = "gats.synthetic-planning-task.v1"
GATS_STRESS_SELECTION_POLICY_DIGEST = canonical_digest({
    "benchmark_id": GATS_SYNTHETIC_BENCHMARK_ID,
    "revision_id": GATS_STRESS_REVISION,
    "generator": GATS_STRESS_SOURCE_PATH,
    "category_order": GATS_STRESS_CATEGORIES,
    "tasks_per_category": GATS_STRESS_TASKS_PER_CATEGORY,
    "selection": "all_generated_tasks_in_generator_order",
})

@dataclass(frozen=True, slots=True)
class GatsStressTaskRecord:
    category: str
    index: int
    content_digest: str

    def __post_init__(self) -> None:
        if self.category not in GATS_STRESS_CATEGORIES:
            raise ValueError("unknown GATS stress category")
        if type(self.index) is not int or not 0 <= self.index < GATS_STRESS_TASKS_PER_CATEGORY:
            raise ValueError("GATS stress category index must be in [0, 10)")
        require_sha256(self.content_digest, "GATS stress task content_digest")

    @property
    def task_id(self) -> str:
        return f"gats-stress:{self.category}:{self.index:02d}"

def build_gats_stress_source_spec(*, content_digest: str) -> BenchmarkSourceSpec:
    require_sha256(content_digest, "GATS stress source content_digest")
    return BenchmarkSourceSpec(
        source_id="gats.synthetic.stress",
        kind=BenchmarkSourceKind.GIT,
        revision_id=GATS_STRESS_REVISION,
        locator=f"{GATS_SOURCE_REPOSITORY}/blob/{GATS_REPRO_SOURCE_COMMIT}/{GATS_STRESS_SOURCE_PATH}",
        content_digest=content_digest,
        metadata={
            "repository": GATS_SOURCE_REPOSITORY,
            "commit": GATS_REPRO_SOURCE_COMMIT,
            "path": GATS_STRESS_SOURCE_PATH,
            "git_blob_sha1": GATS_STRESS_SOURCE_BLOB_SHA1,
            "category_count": str(len(GATS_STRESS_CATEGORIES)),
            "tasks_per_category": str(GATS_STRESS_TASKS_PER_CATEGORY),
        },
    )

def build_gats_stress_task_set(
    records: tuple[GatsStressTaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or any(type(row) is not GatsStressTaskRecord for row in records):
        raise TypeError("GATS stress records must be a tuple of GatsStressTaskRecord")
    require_sha256(source_digest, "GATS stress source_digest")
    by_key = {(row.category, row.index): row for row in records}
    expected = tuple(
        (category, index)
        for category in GATS_STRESS_CATEGORIES
        for index in range(GATS_STRESS_TASKS_PER_CATEGORY)
    )
    if len(records) != GATS_STRESS_TASK_COUNT or set(by_key) != set(expected):
        raise ValueError("GATS stress cut requires exactly 12 categories x 10 tasks")
    ordered = tuple(by_key[key] for key in expected)
    tasks = tuple(sorted((
        TaskDefinition(
            task_id=row.task_id,
            revision_id=GATS_STRESS_REVISION,
            family=row.category,
            schema_id=GATS_STRESS_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"category:{row.category}",
                f"category-index:{row.index}",
                f"source-commit:{GATS_REPRO_SOURCE_COMMIT}",
            ),
        )
        for row in ordered
    ), key=lambda row: row.task_id))
    return BenchmarkTaskSet(
        benchmark_id=GATS_SYNTHETIC_BENCHMARK_ID,
        revision_id=GATS_STRESS_REVISION,
        source_digest=source_digest,
        task_schema_id=GATS_STRESS_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(TaskSetSplit(GATS_STRESS_SPLIT, tuple(row.task_id for row in ordered)),),
        selection_policy_digest=GATS_STRESS_SELECTION_POLICY_DIGEST,
    )

__all__ = [
    "GATS_REPRO_SOURCE_COMMIT",
    "GATS_SOURCE_REPOSITORY",
    "GATS_STRESS_CATEGORIES",
    "GATS_STRESS_REVISION",
    "GATS_STRESS_SELECTION_POLICY_DIGEST",
    "GATS_STRESS_SOURCE_BLOB_SHA1",
    "GATS_STRESS_SOURCE_PATH",
    "GATS_STRESS_SPLIT",
    "GATS_STRESS_TASK_COUNT",
    "GATS_STRESS_TASK_SCHEMA_ID",
    "GATS_STRESS_TASKS_PER_CATEGORY",
    "GATS_SYNTHETIC_BENCHMARK_ID",
    "GatsStressTaskRecord",
    "build_gats_stress_source_spec",
    "build_gats_stress_task_set",
]
