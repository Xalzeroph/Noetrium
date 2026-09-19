from __future__ import annotations

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

HUMANEVAL_BENCHMARK_ID = "humaneval"
HUMANEVAL_REPOSITORY = "https://github.com/openai/human-eval"
HUMANEVAL_PAPER_ERA_COMMIT = "312c5e5532f0e0470bf47f77a6243e02a61da530"
HUMANEVAL_TASK_SCHEMA_ID = "humaneval.python-function-completion.v1"
HUMANEVAL_TASK_COUNT = 164
HUMANEVAL_SPLIT_ID = "test"


@dataclass(frozen=True, slots=True, order=True)
class HumanEvalTaskRecord:
    index: int
    task_id: str
    entry_point: str
    content_digest: str

    def __post_init__(self) -> None:
        if type(self.index) is not int or not 0 <= self.index < HUMANEVAL_TASK_COUNT:
            raise ValueError("HumanEval index must be in [0, 164)")
        expected = f"HumanEval/{self.index}"
        if self.task_id != expected:
            raise ValueError(
                f"HumanEval task identity drift: expected={expected!r} actual={self.task_id!r}"
            )
        if not isinstance(self.entry_point, str) or not self.entry_point.strip():
            raise ValueError("HumanEval entry_point must be non-empty")
        require_sha256(self.content_digest, "HumanEval task content_digest")


def humaneval_revision(dataset_content_sha256: str) -> str:
    require_sha256(dataset_content_sha256, "HumanEval dataset_content_sha256")
    return (
        f"humaneval@repo:{HUMANEVAL_PAPER_ERA_COMMIT}:"
        f"dataset:{dataset_content_sha256}"
    )


def build_humaneval_source(
    *,
    dataset_content_sha256: str,
) -> BenchmarkSourceSpec:
    require_sha256(dataset_content_sha256, "HumanEval dataset_content_sha256")
    return BenchmarkSourceSpec(
        source_id=HUMANEVAL_BENCHMARK_ID,
        kind=BenchmarkSourceKind.CUSTOM,
        revision_id=humaneval_revision(dataset_content_sha256),
        locator=HUMANEVAL_REPOSITORY,
        content_digest=dataset_content_sha256,
        metadata={
            "paper_era_commit": HUMANEVAL_PAPER_ERA_COMMIT,
            "task_count": str(HUMANEVAL_TASK_COUNT),
            "evaluation": "functional_correctness",
            "paper_metrics": "pass@1,pass@10,pass@100",
            "execution_requires_sandbox": "true",
        },
    )


def build_humaneval_task_set(
    records: tuple[HumanEvalTaskRecord, ...],
    *,
    dataset_content_sha256: str,
) -> BenchmarkTaskSet:
    """Freeze the original 164-task HumanEval functional-correctness cut."""

    if type(records) is not tuple or any(
        type(row) is not HumanEvalTaskRecord for row in records
    ):
        raise TypeError("HumanEval records must be a tuple of HumanEvalTaskRecord")
    require_sha256(dataset_content_sha256, "HumanEval dataset_content_sha256")
    if len(records) != HUMANEVAL_TASK_COUNT:
        raise ValueError("HumanEval cut requires exactly 164 tasks")

    by_index = {row.index: row for row in records}
    if len(by_index) != HUMANEVAL_TASK_COUNT or set(by_index) != set(
        range(HUMANEVAL_TASK_COUNT)
    ):
        raise ValueError("HumanEval cut requires one canonical task per index")

    ordered = tuple(by_index[index] for index in range(HUMANEVAL_TASK_COUNT))
    revision = humaneval_revision(dataset_content_sha256)
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=revision,
            family="python_function_completion",
            schema_id=HUMANEVAL_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"source-index:{row.index}",
                f"entry-point:{row.entry_point}",
            ),
            package=TaskPackageSpec(
                package_schema_id="humaneval.python-execution-package.v1",
                instruction_digest=row.content_digest,
                environment_requirement_id="benchmark.humaneval.python-sandbox",
                verifier_requirement_id="benchmark.humaneval.functional-correctness.verifier",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
                artifacts=(
                    TaskArtifactSpec(
                        "humaneval_completion",
                        "completion.py",
                        True,
                    ),
                ),
            ),
        )
        for row in ordered
    )
    task_ids = tuple(row.task_id for row in ordered)
    return BenchmarkTaskSet(
        benchmark_id=HUMANEVAL_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id=HUMANEVAL_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(TaskSetSplit(HUMANEVAL_SPLIT_ID, task_ids),),
        selection_policy_digest=canonical_digest(
            {
                "paper_era_commit": HUMANEVAL_PAPER_ERA_COMMIT,
                "dataset_content_sha256": dataset_content_sha256,
                "task_ids": task_ids,
                "metric": "functional_correctness",
                "verifier_isolation": TaskVerifierIsolation.SEPARATE.value,
            }
        ),
    )


__all__ = [
    "HUMANEVAL_BENCHMARK_ID",
    "HUMANEVAL_PAPER_ERA_COMMIT",
    "HUMANEVAL_REPOSITORY",
    "HUMANEVAL_SPLIT_ID",
    "HUMANEVAL_TASK_COUNT",
    "HUMANEVAL_TASK_SCHEMA_ID",
    "HumanEvalTaskRecord",
    "build_humaneval_source",
    "build_humaneval_task_set",
    "humaneval_revision",
]
