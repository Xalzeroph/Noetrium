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

COMMONGEN_BENCHMARK_ID = "commongen"
COMMONGEN_REPOSITORY = "https://github.com/INK-USC/CommonGen"
COMMONGEN_PAPER_URI = "https://aclanthology.org/2020.findings-emnlp.165/"
COMMONGEN_TASK_SCHEMA_ID = "commongen.concept-set-generation.v1"


@dataclass(frozen=True, slots=True, order=True)
class CommonGenTaskRecord:
    task_id: str
    split_id: str
    concepts: tuple[str, ...]
    content_digest: str
    reference_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("CommonGen task_id must be non-empty")
        if not isinstance(self.split_id, str) or not self.split_id.strip():
            raise ValueError("CommonGen split_id must be non-empty")
        if (
            type(self.concepts) is not tuple
            or not self.concepts
            or any(not isinstance(item, str) or not item.strip() for item in self.concepts)
        ):
            raise TypeError("CommonGen concepts must be a non-empty tuple of text")
        if len(self.concepts) != len(set(self.concepts)):
            raise ValueError("CommonGen concepts must be unique within a task")
        require_sha256(self.content_digest, "CommonGen task content_digest")
        if type(self.reference_count) is not int or self.reference_count < 0:
            raise ValueError("CommonGen reference_count must be non-negative")


def commongen_revision(dataset_revision: str) -> str:
    if not isinstance(dataset_revision, str) or not dataset_revision.strip():
        raise ValueError("CommonGen dataset_revision must be non-empty")
    return f"commongen@dataset:{dataset_revision.strip()}"


def build_commongen_source(
    *,
    dataset_revision: str,
    dataset_content_sha256: str,
) -> BenchmarkSourceSpec:
    require_sha256(dataset_content_sha256, "CommonGen dataset_content_sha256")
    return BenchmarkSourceSpec(
        source_id=COMMONGEN_BENCHMARK_ID,
        kind=BenchmarkSourceKind.CUSTOM,
        revision_id=commongen_revision(dataset_revision),
        locator=COMMONGEN_REPOSITORY,
        content_digest=dataset_content_sha256,
        license="MIT",
        metadata={
            "paper_uri": COMMONGEN_PAPER_URI,
            "task_semantics": "generate_one_sentence_covering_all_concepts",
            "paper_metrics": "BLEU,CIDEr,SPICE,coverage",
        },
    )


def build_commongen_task_set(
    records: tuple[CommonGenTaskRecord, ...],
    *,
    dataset_revision: str,
    dataset_content_sha256: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or not records:
        raise ValueError("CommonGen records must be a non-empty tuple")
    if any(type(row) is not CommonGenTaskRecord for row in records):
        raise TypeError("CommonGen records must contain CommonGenTaskRecord")
    require_sha256(dataset_content_sha256, "CommonGen dataset_content_sha256")

    ordered = tuple(sorted(records, key=lambda row: row.task_id))
    task_ids = tuple(row.task_id for row in ordered)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("CommonGen task ids must be unique")

    revision = commongen_revision(dataset_revision)
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=revision,
            family="generative_commonsense",
            schema_id=COMMONGEN_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"split:{row.split_id}",
                f"concept-count:{len(row.concepts)}",
                f"concepts-digest:{canonical_digest(row.concepts)}",
                f"reference-count:{row.reference_count}",
            ),
            package=TaskPackageSpec(
                package_schema_id="commongen.text-generation-package.v1",
                instruction_digest=row.content_digest,
                environment_requirement_id=None,
                verifier_requirement_id="benchmark.commongen.verifier",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
                artifacts=(
                    TaskArtifactSpec(
                        "commongen_prediction",
                        "prediction.txt",
                        True,
                    ),
                ),
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
    selection_policy_digest = canonical_digest(
        {
            "benchmark_id": COMMONGEN_BENCHMARK_ID,
            "dataset_revision": dataset_revision,
            "dataset_content_sha256": dataset_content_sha256,
            "splits": tuple((row.split_id, row.task_ids) for row in splits),
            "task_concepts": tuple(
                (row.task_id, row.concepts, row.reference_count)
                for row in ordered
            ),
        }
    )
    return BenchmarkTaskSet(
        benchmark_id=COMMONGEN_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id=COMMONGEN_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=splits,
        selection_policy_digest=selection_policy_digest,
    )


__all__ = [
    "COMMONGEN_BENCHMARK_ID",
    "COMMONGEN_PAPER_URI",
    "COMMONGEN_REPOSITORY",
    "COMMONGEN_TASK_SCHEMA_ID",
    "CommonGenTaskRecord",
    "build_commongen_source",
    "build_commongen_task_set",
    "commongen_revision",
]
