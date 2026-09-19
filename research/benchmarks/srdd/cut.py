from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkSourceKind,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskArtifactSpec,
    TaskDefinition,
    TaskPackageSpec,
    TaskSetSplit,
    TaskVerifierIsolation,
)


SRDD_BENCHMARK_ID = "srdd"
SRDD_REPOSITORY = "https://github.com/OpenBMB/ChatDev"
SRDD_DATASET_COMMIT = "31fd994416a251ecdeb1f0a73c329271743bfb56"
SRDD_DATASET_PATH = "SRDD/data/data_attribute_format.csv"
SRDD_DATASET_GIT_BLOB_SHA1 = "a319baad413f307b7f0e8dac20018a372ac086bb"
SRDD_LICENSE = "CC-BY-NC-4.0"
SRDD_TASK_SCHEMA_ID = "srdd.software-requirement-description.v1"
SRDD_TASK_COUNT = 1200
SRDD_SUBCATEGORY_COUNT = 40
SRDD_TASKS_PER_SUBCATEGORY = 30
SRDD_MAIN_AREAS = ("Education", "Work", "Life", "Game", "Creation")
SRDD_SPLIT_ID = "all"
SRDD_SOURCE_CONTENT_DIGEST = canonical_digest({
    "repository": SRDD_REPOSITORY,
    "commit": SRDD_DATASET_COMMIT,
    "path": SRDD_DATASET_PATH,
    "git_blob_sha1": SRDD_DATASET_GIT_BLOB_SHA1,
})


@dataclass(frozen=True, slots=True, order=True)
class SrddTaskRecord:
    index: int
    software_name: str
    category: str
    content_digest: str

    def __post_init__(self) -> None:
        if type(self.index) is not int or not 0 <= self.index < SRDD_TASK_COUNT:
            raise ValueError("SRDD index must be in [0, 1200)")
        for field_name in ("software_name", "category"):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"SRDD {field_name} must be non-empty")
        require_sha256(self.content_digest, "SRDD task content_digest")

    @property
    def task_id(self) -> str:
        return f"srdd:{self.index:04d}"


def srdd_revision() -> str:
    return (
        f"srdd@repo:{SRDD_DATASET_COMMIT}:"
        f"blob:{SRDD_DATASET_GIT_BLOB_SHA1}"
    )


def build_srdd_source() -> BenchmarkSourceSpec:
    return BenchmarkSourceSpec(
        source_id=SRDD_BENCHMARK_ID,
        kind=BenchmarkSourceKind.CUSTOM,
        revision_id=srdd_revision(),
        locator=SRDD_REPOSITORY,
        content_digest=SRDD_SOURCE_CONTENT_DIGEST,
        license=SRDD_LICENSE,
        metadata={
            "dataset_commit": SRDD_DATASET_COMMIT,
            "dataset_path": SRDD_DATASET_PATH,
            "dataset_git_blob_sha1": SRDD_DATASET_GIT_BLOB_SHA1,
            "task_count": str(SRDD_TASK_COUNT),
            "main_areas": ",".join(SRDD_MAIN_AREAS),
            "subcategory_count": str(SRDD_SUBCATEGORY_COUNT),
            "tasks_per_subcategory": str(SRDD_TASKS_PER_SUBCATEGORY),
            "paper_metrics": (
                "completeness,executability,consistency,quality"
            ),
        },
    )


def build_srdd_task_set(
    records: tuple[SrddTaskRecord, ...],
) -> BenchmarkTaskSet:
    """Freeze the official 1,200-task SRDD cut used by ChatDev evaluation."""

    if type(records) is not tuple or any(
        type(row) is not SrddTaskRecord for row in records
    ):
        raise TypeError("SRDD records must be a tuple of SrddTaskRecord")
    if len(records) != SRDD_TASK_COUNT:
        raise ValueError("SRDD cut requires exactly 1200 tasks")

    by_index = {row.index: row for row in records}
    if len(by_index) != SRDD_TASK_COUNT or set(by_index) != set(
        range(SRDD_TASK_COUNT)
    ):
        raise ValueError("SRDD cut requires one canonical task per source index")

    ordered = tuple(by_index[index] for index in range(SRDD_TASK_COUNT))
    names = tuple(row.software_name for row in ordered)
    if len(names) != len(set(names)):
        raise ValueError("SRDD software names must be unique")

    category_counts = Counter(row.category for row in ordered)
    if len(category_counts) != SRDD_SUBCATEGORY_COUNT:
        raise ValueError("SRDD cut requires exactly 40 subcategories")
    if set(category_counts.values()) != {SRDD_TASKS_PER_SUBCATEGORY}:
        raise ValueError("each SRDD subcategory must contain exactly 30 tasks")

    revision = srdd_revision()
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=revision,
            family=row.category,
            schema_id=SRDD_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"source-index:{row.index}",
                f"software-name:{row.software_name}",
                f"subcategory:{row.category}",
            ),
            package=TaskPackageSpec(
                package_schema_id="srdd.software-project-package.v1",
                instruction_digest=row.content_digest,
                environment_requirement_id=(
                    "benchmark.srdd.software-repository"
                ),
                verifier_requirement_id=(
                    "benchmark.srdd.chatdev-paper-metrics.verifier"
                ),
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
                artifacts=(
                    TaskArtifactSpec(
                        "generated_software_repository",
                        "workspace.tar.gz",
                        True,
                    ),
                ),
            ),
        )
        for row in ordered
    )
    task_ids = tuple(row.task_id for row in ordered)
    category_splits = tuple(
        TaskSetSplit(
            f"category:{category}",
            tuple(
                row.task_id
                for row in ordered
                if row.category == category
            ),
        )
        for category in sorted(category_counts)
    )
    return BenchmarkTaskSet(
        benchmark_id=SRDD_BENCHMARK_ID,
        revision_id=revision,
        source_digest=SRDD_SOURCE_CONTENT_DIGEST,
        task_schema_id=SRDD_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(
            TaskSetSplit(SRDD_SPLIT_ID, task_ids),
            *category_splits,
        ),
        selection_policy_digest=canonical_digest({
            "dataset_commit": SRDD_DATASET_COMMIT,
            "dataset_path": SRDD_DATASET_PATH,
            "dataset_git_blob_sha1": SRDD_DATASET_GIT_BLOB_SHA1,
            "task_ids": task_ids,
            "category_counts": tuple(sorted(category_counts.items())),
            "metrics": (
                "completeness",
                "executability",
                "consistency",
                "quality",
            ),
        }),
    )


__all__ = [
    "SRDD_BENCHMARK_ID",
    "SRDD_DATASET_COMMIT",
    "SRDD_DATASET_GIT_BLOB_SHA1",
    "SRDD_DATASET_PATH",
    "SRDD_LICENSE",
    "SRDD_MAIN_AREAS",
    "SRDD_REPOSITORY",
    "SRDD_SOURCE_CONTENT_DIGEST",
    "SRDD_SPLIT_ID",
    "SRDD_SUBCATEGORY_COUNT",
    "SRDD_TASKS_PER_SUBCATEGORY",
    "SRDD_TASK_COUNT",
    "SRDD_TASK_SCHEMA_ID",
    "SrddTaskRecord",
    "build_srdd_source",
    "build_srdd_task_set",
    "srdd_revision",
]
