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

MIND2WEB_BENCHMARK_ID = "mind2web"
MIND2WEB_REPOSITORY = "https://github.com/OSU-NLP-Group/Mind2Web"
MIND2WEB_DATASET_LOCATOR = "https://huggingface.co/datasets/osunlp/Mind2Web"
MIND2WEB_EVALUATOR_COMMIT = "b19eba7f40042425cbff44f0ccba9572bcef1344"
MIND2WEB_TASK_SCHEMA_ID = "mind2web.offline-web-action-task.v1"

MIND2WEB_SPLIT_COUNTS = {
    "test_task": 252,
    "test_website": 177,
    "test_domain": 912,
}


@dataclass(frozen=True, slots=True, order=True)
class Mind2WebTaskRecord:
    annotation_id: str
    website: str
    domain: str
    subdomain: str
    split_id: str
    content_digest: str
    step_count: int

    def __post_init__(self) -> None:
        for field_name in (
            "annotation_id",
            "website",
            "domain",
            "subdomain",
            "split_id",
        ):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"Mind2Web {field_name} must be non-empty")
        if self.split_id not in MIND2WEB_SPLIT_COUNTS:
            raise ValueError(f"unsupported Mind2Web split: {self.split_id!r}")
        require_sha256(self.content_digest, "Mind2Web task content_digest")
        if type(self.step_count) is not int or self.step_count <= 0:
            raise ValueError("Mind2Web step_count must be positive")


def mind2web_revision(dataset_revision: str) -> str:
    if type(dataset_revision) is not str or not dataset_revision.strip():
        raise ValueError("Mind2Web dataset_revision must be non-empty")
    return (
        f"mind2web@dataset:{dataset_revision.strip()}:"
        f"evaluator:{MIND2WEB_EVALUATOR_COMMIT}"
    )


def build_mind2web_source(
    *,
    dataset_revision: str,
    dataset_content_sha256: str,
) -> BenchmarkSourceSpec:
    require_sha256(dataset_content_sha256, "Mind2Web dataset_content_sha256")
    return BenchmarkSourceSpec(
        source_id=MIND2WEB_BENCHMARK_ID,
        kind=BenchmarkSourceKind.HUGGINGFACE,
        revision_id=mind2web_revision(dataset_revision),
        locator=MIND2WEB_DATASET_LOCATOR,
        content_digest=dataset_content_sha256,
        license="CC-BY-4.0",
        metadata={
            "code_repository": MIND2WEB_REPOSITORY,
            "evaluator_commit": MIND2WEB_EVALUATOR_COMMIT,
            "paper_metric_aggregation": "macro_average",
            "task_semantics": "offline_stepwise_web_action_prediction",
        },
    )


def build_mind2web_task_set(
    records: tuple[Mind2WebTaskRecord, ...],
    *,
    dataset_revision: str,
    dataset_content_sha256: str,
    require_paper_split_cardinality: bool = True,
) -> BenchmarkTaskSet:
    """Freeze Mind2Web tasks without importing its training/evaluation runtime."""

    if type(records) is not tuple or not records:
        raise ValueError("Mind2Web records must be a non-empty tuple")
    if any(type(row) is not Mind2WebTaskRecord for row in records):
        raise TypeError("Mind2Web records must contain Mind2WebTaskRecord")
    require_sha256(dataset_content_sha256, "Mind2Web dataset_content_sha256")

    ordered = tuple(sorted(records, key=lambda row: row.annotation_id))
    task_ids = tuple(row.annotation_id for row in ordered)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Mind2Web annotation ids must be unique")

    if require_paper_split_cardinality:
        counts = {
            split: sum(row.split_id == split for row in ordered)
            for split in MIND2WEB_SPLIT_COUNTS
        }
        present = {row.split_id for row in ordered}
        for split in present:
            if counts[split] != MIND2WEB_SPLIT_COUNTS[split]:
                raise ValueError(
                    f"Mind2Web {split} requires paper cardinality "
                    f"{MIND2WEB_SPLIT_COUNTS[split]}, got {counts[split]}"
                )

    revision = mind2web_revision(dataset_revision)
    tasks = tuple(
        TaskDefinition(
            task_id=row.annotation_id,
            revision_id=revision,
            family=row.domain,
            schema_id=MIND2WEB_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"website:{row.website}",
                f"domain:{row.domain}",
                f"subdomain:{row.subdomain}",
                f"steps:{row.step_count}",
            ),
            package=TaskPackageSpec(
                package_schema_id="mind2web.offline-action-package.v1",
                instruction_digest=row.content_digest,
                environment_requirement_id=None,
                verifier_requirement_id="benchmark.mind2web.action.verifier",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for row in ordered
    )
    split_names = tuple(sorted({row.split_id for row in ordered}))
    splits = tuple(
        TaskSetSplit(
            split_id,
            tuple(row.annotation_id for row in ordered if row.split_id == split_id),
        )
        for split_id in split_names
    )
    selection_policy_digest = canonical_digest(
        {
            "benchmark_id": MIND2WEB_BENCHMARK_ID,
            "dataset_revision": dataset_revision,
            "evaluator_commit": MIND2WEB_EVALUATOR_COMMIT,
            "aggregation": "macro_average",
            "splits": tuple((split.split_id, split.task_ids) for split in splits),
        }
    )
    return BenchmarkTaskSet(
        benchmark_id=MIND2WEB_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id=MIND2WEB_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=splits,
        selection_policy_digest=selection_policy_digest,
    )


__all__ = [
    "MIND2WEB_BENCHMARK_ID",
    "MIND2WEB_DATASET_LOCATOR",
    "MIND2WEB_EVALUATOR_COMMIT",
    "MIND2WEB_REPOSITORY",
    "MIND2WEB_SPLIT_COUNTS",
    "MIND2WEB_TASK_SCHEMA_ID",
    "Mind2WebTaskRecord",
    "build_mind2web_source",
    "build_mind2web_task_set",
    "mind2web_revision",
]
