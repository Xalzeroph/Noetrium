from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    TaskDefinition,
    TaskPackageSpec,
    TaskSetSplit,
    TaskVerifierIsolation,
)

HUGGINGGPT_BENCHMARK_ID = "hugginggpt-paper-tasks"
HUGGINGGPT_SPLIT_ID = "paper-era"
HUGGINGGPT_SOURCE_COMMIT = "2c19142b56663a54b2c85f8622b38f98c5b2580f"


@dataclass(frozen=True, slots=True, order=True)
class HuggingGPTPaperTaskRecord:
    task_id: str
    instruction: str
    content_digest: str
    modalities: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.task_id) is not str or not self.task_id.strip():
            raise ValueError("HuggingGPT task_id is required")
        if type(self.instruction) is not str or not self.instruction.strip():
            raise ValueError("HuggingGPT instruction is required")
        require_sha256(self.content_digest, "HuggingGPT task content_digest")
        if type(self.modalities) is not tuple or not self.modalities:
            raise ValueError("HuggingGPT modalities are required")
        if any(type(row) is not str or not row.strip() for row in self.modalities):
            raise ValueError("HuggingGPT modalities must be canonical text")


def build_hugginggpt_paper_task_set(
    records: tuple[HuggingGPTPaperTaskRecord, ...],
    *,
    dataset_content_sha256: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or not records:
        raise ValueError("HuggingGPT paper task records must be non-empty")
    if any(type(row) is not HuggingGPTPaperTaskRecord for row in records):
        raise TypeError("HuggingGPT records must be typed")
    require_sha256(dataset_content_sha256, "HuggingGPT dataset_content_sha256")
    ordered = tuple(sorted(records, key=lambda row: row.task_id))
    task_ids = tuple(row.task_id for row in ordered)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("HuggingGPT task ids must be unique")
    revision = (
        f"hugginggpt@{HUGGINGGPT_SOURCE_COMMIT}:dataset:{dataset_content_sha256}"
    )
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=revision,
            family="hugginggpt_multimodal_orchestration",
            schema_id="hugginggpt.paper-task.v1",
            content_digest=row.content_digest,
            lineage_refs=(
                f"source-commit:{HUGGINGGPT_SOURCE_COMMIT}",
                *tuple(f"modality:{modality}" for modality in row.modalities),
            ),
            package=TaskPackageSpec(
                package_schema_id="hugginggpt.paper-task-package.v1",
                instruction_digest=canonical_digest(row.instruction),
                environment_requirement_id=None,
                verifier_requirement_id="benchmark.hugginggpt.task-completion",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for row in ordered
    )
    return BenchmarkTaskSet(
        benchmark_id=HUGGINGGPT_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id="hugginggpt.paper-task.v1",
        tasks=tasks,
        splits=(
            TaskSetSplit("all", task_ids),
            TaskSetSplit(HUGGINGGPT_SPLIT_ID, task_ids),
        ),
        selection_policy_digest=canonical_digest({
            "source_commit": HUGGINGGPT_SOURCE_COMMIT,
            "dataset_content_sha256": dataset_content_sha256,
            "task_ids": task_ids,
        }),
    )


__all__ = [
    "HUGGINGGPT_BENCHMARK_ID",
    "HUGGINGGPT_SOURCE_COMMIT",
    "HUGGINGGPT_SPLIT_ID",
    "HuggingGPTPaperTaskRecord",
    "build_hugginggpt_paper_task_set",
]
