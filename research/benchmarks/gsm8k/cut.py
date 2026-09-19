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
    TaskVerifierIsolation,
)

GSM8K_BENCHMARK_ID = "gsm8k"
GSM8K_REPOSITORY = "https://github.com/openai/grade-school-math"
GSM8K_RELEASE_COMMIT = "b0bb162abedc65e1fdd8e93ed090fd7598ee68bc"
GSM8K_ARCHIVED_COMMIT = "3101c7d5072418e28b9008a6636bde82a006892c"
GSM8K_TASK_SCHEMA_ID = "gsm8k.grade-school-math.v1"
GSM8K_SPLIT_COUNTS = {"train": 7473, "test": 1319}
GSM8K_FINAL_ANSWER_MARKER = "####"


@dataclass(frozen=True, slots=True, order=True)
class GSM8KTaskRecord:
    split_id: str
    index: int
    question_digest: str
    answer_digest: str
    content_digest: str

    def __post_init__(self) -> None:
        if self.split_id not in GSM8K_SPLIT_COUNTS:
            raise ValueError(f"unsupported GSM8K split: {self.split_id!r}")
        limit = GSM8K_SPLIT_COUNTS[self.split_id]
        if type(self.index) is not int or not 0 <= self.index < limit:
            raise ValueError(
                f"GSM8K {self.split_id} index must be in [0, {limit})"
            )
        require_sha256(self.question_digest, "GSM8K question_digest")
        require_sha256(self.answer_digest, "GSM8K answer_digest")
        require_sha256(self.content_digest, "GSM8K content_digest")

    @property
    def task_id(self) -> str:
        return f"gsm8k:{self.split_id}:{self.index:05d}"


def gsm8k_revision(dataset_content_sha256: str) -> str:
    require_sha256(dataset_content_sha256, "GSM8K dataset_content_sha256")
    return (
        f"gsm8k@repo:{GSM8K_ARCHIVED_COMMIT}:"
        f"dataset:{dataset_content_sha256}"
    )


def build_gsm8k_source(*, dataset_content_sha256: str) -> BenchmarkSourceSpec:
    require_sha256(dataset_content_sha256, "GSM8K dataset_content_sha256")
    return BenchmarkSourceSpec(
        source_id=GSM8K_BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=gsm8k_revision(dataset_content_sha256),
        locator=GSM8K_REPOSITORY,
        content_digest=dataset_content_sha256,
        license="MIT",
        metadata={
            "release_commit": GSM8K_RELEASE_COMMIT,
            "archived_commit": GSM8K_ARCHIVED_COMMIT,
            "train_count": str(GSM8K_SPLIT_COUNTS["train"]),
            "test_count": str(GSM8K_SPLIT_COUNTS["test"]),
            "answer_format": "final numeric answer follows #### marker",
        },
    )


def build_gsm8k_task_set(
    records: tuple[GSM8KTaskRecord, ...],
    *,
    dataset_content_sha256: str,
    require_full_split_cardinality: bool = True,
) -> BenchmarkTaskSet:
    """Freeze the official GSM8K JSONL cut without importing its runtime."""

    if type(records) is not tuple or not records:
        raise ValueError("GSM8K records must be a non-empty tuple")
    if any(type(row) is not GSM8KTaskRecord for row in records):
        raise TypeError("GSM8K records must contain GSM8KTaskRecord")
    require_sha256(dataset_content_sha256, "GSM8K dataset_content_sha256")

    ordered = tuple(sorted(records, key=lambda row: (row.split_id, row.index)))
    task_ids = tuple(row.task_id for row in ordered)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("GSM8K task ids must be unique")

    if require_full_split_cardinality:
        present = {row.split_id for row in ordered}
        for split_id in present:
            actual = sum(row.split_id == split_id for row in ordered)
            expected = GSM8K_SPLIT_COUNTS[split_id]
            if actual != expected:
                raise ValueError(
                    f"GSM8K {split_id} requires {expected} tasks, got {actual}"
                )

    revision = gsm8k_revision(dataset_content_sha256)
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=revision,
            family="grade_school_math",
            schema_id=GSM8K_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"split:{row.split_id}",
                f"source-index:{row.index}",
                f"question-digest:{row.question_digest}",
                f"answer-digest:{row.answer_digest}",
                f"answer-marker:{GSM8K_FINAL_ANSWER_MARKER}",
            ),
            package=TaskPackageSpec(
                package_schema_id="gsm8k.free-response-package.v1",
                instruction_digest=row.question_digest,
                environment_requirement_id=None,
                verifier_requirement_id="benchmark.gsm8k.exact-numeric.verifier",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for row in ordered
    )
    split_ids = tuple(sorted({row.split_id for row in ordered}))
    splits = tuple(
        TaskSetSplit(
            split_id,
            tuple(row.task_id for row in ordered if row.split_id == split_id),
        )
        for split_id in split_ids
    )
    return BenchmarkTaskSet(
        benchmark_id=GSM8K_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id=GSM8K_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=splits,
        selection_policy_digest=canonical_digest(
            {
                "repository": GSM8K_REPOSITORY,
                "release_commit": GSM8K_RELEASE_COMMIT,
                "archived_commit": GSM8K_ARCHIVED_COMMIT,
                "dataset_content_sha256": dataset_content_sha256,
                "splits": tuple((row.split_id, row.task_ids) for row in splits),
                "answer_marker": GSM8K_FINAL_ANSWER_MARKER,
                "verifier_isolation": TaskVerifierIsolation.SEPARATE.value,
            }
        ),
    )


__all__ = [
    "GSM8K_ARCHIVED_COMMIT",
    "GSM8K_BENCHMARK_ID",
    "GSM8K_FINAL_ANSWER_MARKER",
    "GSM8K_RELEASE_COMMIT",
    "GSM8K_REPOSITORY",
    "GSM8K_SPLIT_COUNTS",
    "GSM8K_TASK_SCHEMA_ID",
    "GSM8KTaskRecord",
    "build_gsm8k_source",
    "build_gsm8k_task_set",
    "gsm8k_revision",
]
