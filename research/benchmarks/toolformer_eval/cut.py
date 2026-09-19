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

TOOLFORMER_BENCHMARK_ID = "toolformer-eval"
TOOLFORMER_SPLIT_ID = "paper-zero-shot"
TOOLFORMER_DATASETS = (
    "SQuAD",
    "Google-RE",
    "T-REx",
    "ASDiv",
    "SVAMP",
    "MAWPS",
)


@dataclass(frozen=True, slots=True, order=True)
class ToolformerEvalRecord:
    dataset: str
    task_id: str
    instruction: str
    content_digest: str

    def __post_init__(self) -> None:
        if self.dataset not in TOOLFORMER_DATASETS:
            raise ValueError(f"unsupported Toolformer paper dataset: {self.dataset!r}")
        if type(self.task_id) is not str or not self.task_id.strip():
            raise ValueError("Toolformer task_id is required")
        if type(self.instruction) is not str or not self.instruction.strip():
            raise ValueError("Toolformer instruction is required")
        require_sha256(self.content_digest, "Toolformer task content_digest")


def build_toolformer_eval_task_set(
    records: tuple[ToolformerEvalRecord, ...],
    *,
    dataset_content_sha256: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or not records:
        raise ValueError("Toolformer evaluation records must be non-empty")
    if any(type(row) is not ToolformerEvalRecord for row in records):
        raise TypeError("Toolformer evaluation records must be typed")
    require_sha256(dataset_content_sha256, "Toolformer dataset_content_sha256")
    ordered = tuple(sorted(records, key=lambda row: row.task_id))
    ids = tuple(row.task_id for row in ordered)
    if len(ids) != len(set(ids)):
        raise ValueError("Toolformer task ids must be unique")
    revision = f"neurips2023:toolformer-eval:{dataset_content_sha256}"
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=revision,
            family=row.dataset.lower().replace("-", "_"),
            schema_id="toolformer.zero-shot-task.v1",
            content_digest=row.content_digest,
            lineage_refs=(
                f"dataset:{row.dataset}",
                "paper-mode:zero-shot",
            ),
            package=TaskPackageSpec(
                package_schema_id="toolformer.zero-shot-package.v1",
                instruction_digest=canonical_digest(row.instruction),
                environment_requirement_id=None,
                verifier_requirement_id="benchmark.toolformer.zero-shot",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for row in ordered
    )
    return BenchmarkTaskSet(
        benchmark_id=TOOLFORMER_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id="toolformer.zero-shot-task.v1",
        tasks=tasks,
        splits=tuple(sorted(
            (
                TaskSetSplit("all", ids),
                TaskSetSplit(TOOLFORMER_SPLIT_ID, ids),
                *tuple(
                    TaskSetSplit(
                        f"dataset:{dataset}",
                        tuple(row.task_id for row in ordered if row.dataset == dataset),
                    )
                    for dataset in TOOLFORMER_DATASETS
                    if any(row.dataset == dataset for row in ordered)
                ),
            ),
            key=lambda split: split.split_id,
        )),
        selection_policy_digest=canonical_digest({
            "datasets": TOOLFORMER_DATASETS,
            "dataset_content_sha256": dataset_content_sha256,
            "task_ids": ids,
        }),
    )


__all__ = [
    "TOOLFORMER_BENCHMARK_ID",
    "TOOLFORMER_DATASETS",
    "TOOLFORMER_SPLIT_ID",
    "ToolformerEvalRecord",
    "build_toolformer_eval_task_set",
]
