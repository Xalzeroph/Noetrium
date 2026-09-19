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

CAMEL_AI_SOCIETY_BENCHMARK_ID = "camel-ai-society"
CAMEL_AI_SOCIETY_REPOSITORY = "https://github.com/camel-ai/camel"
CAMEL_AI_SOCIETY_SOURCE_COMMIT = "6915c00a69447fecb796702dc30dec03681173ac"
CAMEL_AI_SOCIETY_TASK_SCHEMA_ID = "camel.ai-society.role-task.v1"
CAMEL_AI_SOCIETY_POPULATION_SIZE = 25_000
CAMEL_AI_SOCIETY_EVALUATION_SIZE = 100
CAMEL_AI_SOCIETY_SPLIT_ID = "agent-eval-100"


@dataclass(frozen=True, slots=True, order=True)
class CamelAISocietyTaskRecord:
    assistant_index: int
    user_index: int
    task_index: int
    assistant_role: str
    user_role: str
    original_task: str
    content_digest: str

    def __post_init__(self) -> None:
        if type(self.assistant_index) is not int or not 1 <= self.assistant_index <= 50:
            raise ValueError("CAMEL assistant_index must be in [1, 50]")
        if type(self.user_index) is not int or not 1 <= self.user_index <= 50:
            raise ValueError("CAMEL user_index must be in [1, 50]")
        if type(self.task_index) is not int or not 1 <= self.task_index <= 10:
            raise ValueError("CAMEL task_index must be in [1, 10]")
        for field_name in ("assistant_role", "user_role", "original_task"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"CAMEL {field_name} must be non-empty")
        require_sha256(self.content_digest, "CAMEL task content_digest")

    @property
    def task_id(self) -> str:
        return (
            f"camel-ai-society:{self.assistant_index:03}:"
            f"{self.user_index:03}:{self.task_index:03}"
        )


def camel_ai_society_revision(dataset_content_sha256: str) -> str:
    require_sha256(dataset_content_sha256, "CAMEL AI Society dataset_content_sha256")
    return (
        f"camel-ai-society@code:{CAMEL_AI_SOCIETY_SOURCE_COMMIT}:"
        f"dataset:{dataset_content_sha256}"
    )


def build_camel_ai_society_source(
    *,
    dataset_content_sha256: str,
) -> BenchmarkSourceSpec:
    require_sha256(dataset_content_sha256, "CAMEL AI Society dataset_content_sha256")
    return BenchmarkSourceSpec(
        source_id=CAMEL_AI_SOCIETY_BENCHMARK_ID,
        kind=BenchmarkSourceKind.CUSTOM,
        revision_id=camel_ai_society_revision(dataset_content_sha256),
        locator=CAMEL_AI_SOCIETY_REPOSITORY,
        content_digest=dataset_content_sha256,
        license="Apache-2.0",
        metadata={
            "source_commit": CAMEL_AI_SOCIETY_SOURCE_COMMIT,
            "population_size": str(CAMEL_AI_SOCIETY_POPULATION_SIZE),
            "paper_agent_evaluation_sample_size": str(CAMEL_AI_SOCIETY_EVALUATION_SIZE),
            "paper_evaluation": "human_pairwise_and_gpt4_pairwise",
            "single_shot_baseline": "gpt-3.5-turbo",
        },
    )


def build_camel_ai_society_task_set(
    records: tuple[CamelAISocietyTaskRecord, ...],
    *,
    dataset_content_sha256: str,
    require_paper_evaluation_size: bool = True,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or not records:
        raise ValueError("CAMEL AI Society records must be a non-empty tuple")
    if any(type(row) is not CamelAISocietyTaskRecord for row in records):
        raise TypeError("CAMEL AI Society records must contain CamelAISocietyTaskRecord")
    require_sha256(dataset_content_sha256, "CAMEL AI Society dataset_content_sha256")
    if require_paper_evaluation_size and len(records) != CAMEL_AI_SOCIETY_EVALUATION_SIZE:
        raise ValueError(
            "CAMEL paper agent evaluation requires exactly "
            f"{CAMEL_AI_SOCIETY_EVALUATION_SIZE} sampled AI Society tasks"
        )

    ordered = tuple(sorted(records, key=lambda row: row.task_id))
    task_ids = tuple(row.task_id for row in ordered)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("CAMEL AI Society task ids must be unique")

    revision = camel_ai_society_revision(dataset_content_sha256)
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=revision,
            family="ai_society",
            schema_id=CAMEL_AI_SOCIETY_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"assistant-role:{row.assistant_role}",
                f"user-role:{row.user_role}",
                f"assistant-index:{row.assistant_index}",
                f"user-index:{row.user_index}",
                f"task-index:{row.task_index}",
            ),
            package=TaskPackageSpec(
                package_schema_id="camel.ai-society-agent-eval-package.v1",
                instruction_digest=row.content_digest,
                environment_requirement_id=None,
                verifier_requirement_id="benchmark.camel-ai-society.pairwise-judge",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
                artifacts=(
                    TaskArtifactSpec("camel_transcript", "transcript.json", True),
                    TaskArtifactSpec("camel_summary", "summary.txt", True),
                    TaskArtifactSpec("single_shot_baseline", "baseline.txt", True),
                ),
            ),
        )
        for row in ordered
    )
    selection_policy_digest = canonical_digest(
        {
            "source_commit": CAMEL_AI_SOCIETY_SOURCE_COMMIT,
            "dataset_content_sha256": dataset_content_sha256,
            "population_size": CAMEL_AI_SOCIETY_POPULATION_SIZE,
            "evaluation_size": len(ordered),
            "paper_sample_size_required": require_paper_evaluation_size,
            "task_ids": task_ids,
            "role_task_identities": tuple(
                (
                    row.task_id,
                    row.assistant_role,
                    row.user_role,
                    canonical_digest(row.original_task),
                )
                for row in ordered
            ),
        }
    )
    return BenchmarkTaskSet(
        benchmark_id=CAMEL_AI_SOCIETY_BENCHMARK_ID,
        revision_id=revision,
        source_digest=dataset_content_sha256,
        task_schema_id=CAMEL_AI_SOCIETY_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(TaskSetSplit(CAMEL_AI_SOCIETY_SPLIT_ID, task_ids),),
        selection_policy_digest=selection_policy_digest,
    )


__all__ = [
    "CAMEL_AI_SOCIETY_BENCHMARK_ID",
    "CAMEL_AI_SOCIETY_EVALUATION_SIZE",
    "CAMEL_AI_SOCIETY_POPULATION_SIZE",
    "CAMEL_AI_SOCIETY_REPOSITORY",
    "CAMEL_AI_SOCIETY_SOURCE_COMMIT",
    "CAMEL_AI_SOCIETY_SPLIT_ID",
    "CAMEL_AI_SOCIETY_TASK_SCHEMA_ID",
    "CamelAISocietyTaskRecord",
    "build_camel_ai_society_source",
    "build_camel_ai_society_task_set",
    "camel_ai_society_revision",
]
