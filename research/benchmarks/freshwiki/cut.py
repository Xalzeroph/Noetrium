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

FRESHWIKI_BENCHMARK_ID = "freshwiki"
FRESHWIKI_SPLIT_ID = "paper-eval"
FRESHWIKI_PAPER_TASK_COUNT = 100


@dataclass(frozen=True, slots=True, order=True)
class FreshWikiTopicRecord:
    topic_id: str
    topic: str
    reference_article_content_sha256: str

    def __post_init__(self) -> None:
        if type(self.topic_id) is not str or not self.topic_id.strip():
            raise ValueError("FreshWiki topic_id is required")
        if type(self.topic) is not str or not self.topic.strip():
            raise ValueError("FreshWiki topic is required")
        require_sha256(
            self.reference_article_content_sha256,
            "FreshWiki reference article digest",
        )

    @property
    def task_content_digest(self) -> str:
        return canonical_digest({
            "topic_id": self.topic_id,
            "topic": self.topic,
            "reference_article_content_sha256": (
                self.reference_article_content_sha256
            ),
        })


def build_freshwiki_task_set(
    records: tuple[FreshWikiTopicRecord, ...],
    *,
    dataset_content_sha256: str,
    require_paper_cardinality: bool = True,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or not records:
        raise ValueError("FreshWiki records must be a non-empty tuple")
    if any(type(row) is not FreshWikiTopicRecord for row in records):
        raise TypeError("FreshWiki records must be typed")
    require_sha256(dataset_content_sha256, "FreshWiki dataset_content_sha256")
    ordered = tuple(sorted(records, key=lambda row: row.topic_id))
    ids = tuple(row.topic_id for row in ordered)
    if len(ids) != len(set(ids)):
        raise ValueError("FreshWiki topic ids must be unique")
    if require_paper_cardinality and len(ordered) != FRESHWIKI_PAPER_TASK_COUNT:
        raise ValueError(
            "FreshWiki paper evaluation requires exactly "
            f"{FRESHWIKI_PAPER_TASK_COUNT} topics"
        )

    revision = f"freshwiki:naacl2024:{dataset_content_sha256}"
    tasks = tuple(
        TaskDefinition(
            task_id=row.topic_id,
            revision_id=revision,
            family="wikipedia_article_generation",
            schema_id="freshwiki.topic.v1",
            content_digest=row.task_content_digest,
            lineage_refs=(
                f"topic:{row.topic}",
                (
                    "reference-article-sha256:"
                    f"{row.reference_article_content_sha256}"
                ),
            ),
            package=TaskPackageSpec(
                package_schema_id="freshwiki.article-generation-package.v1",
                instruction_digest=canonical_digest({
                    "topic": row.topic,
                    "objective": (
                        "write a grounded Wikipedia-like article from scratch"
                    ),
                }),
                environment_requirement_id=None,
                verifier_requirement_id="benchmark.freshwiki.article-quality",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for row in ordered
    )
    return BenchmarkTaskSet(
        benchmark_id=FRESHWIKI_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id="freshwiki.topic.v1",
        tasks=tasks,
        splits=(
            TaskSetSplit("all", ids),
            TaskSetSplit(FRESHWIKI_SPLIT_ID, ids),
        ),
        selection_policy_digest=canonical_digest({
            "dataset_content_sha256": dataset_content_sha256,
            "task_ids": ids,
            "paper_task_count": FRESHWIKI_PAPER_TASK_COUNT,
            "outline_metrics": (
                "heading_soft_recall",
                "heading_entity_recall",
            ),
            "article_metrics": (
                "rouge",
                "entity_recall",
                "rubric_grading",
            ),
        }),
    )


__all__ = [
    "FRESHWIKI_BENCHMARK_ID",
    "FRESHWIKI_PAPER_TASK_COUNT",
    "FRESHWIKI_SPLIT_ID",
    "FreshWikiTopicRecord",
    "build_freshwiki_task_set",
]
