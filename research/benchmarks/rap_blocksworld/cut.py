from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    TaskDefinition,
    TaskSetSplit,
)

RAP_BLOCKSWORLD_BENCHMARK_ID = "blocksworld"
RAP_BLOCKSWORLD_STEP4_REVISION = "rap@774817c2:step_4"
RAP_BLOCKSWORLD_STEP4_SPLIT = "paper_step_4"
RAP_BLOCKSWORLD_STEP4_TASK_COUNT = 57
RAP_BLOCKSWORLD_TASK_SCHEMA_ID = "blocksworld.pddl-task.v1"
RAP_BLOCKSWORLD_SELECTION_POLICY_DIGEST = canonical_digest(
    {
        "benchmark_id": RAP_BLOCKSWORLD_BENCHMARK_ID,
        "revision": RAP_BLOCKSWORLD_STEP4_REVISION,
        "source_artifact": "data/blocksworld/step_4.json",
        "expected_task_count": RAP_BLOCKSWORLD_STEP4_TASK_COUNT,
        "ground_truth_plan_length": 4,
        "selection": "released_json_order",
    }
)


@dataclass(frozen=True, slots=True)
class RapBlocksworldTaskRecord:
    pddl_path: str
    content_digest: str
    ground_truth_plan_length: int = 4

    def __post_init__(self) -> None:
        if type(self.pddl_path) is not str or not self.pddl_path.strip():
            raise ValueError("RAP Blocksworld pddl_path must be non-empty")
        normalized = self.pddl_path.replace("\\", "/").strip()
        if not normalized.endswith(".pddl") or normalized.startswith("../") or "/../" in normalized:
            raise ValueError("RAP Blocksworld pddl_path must identify a dataset PDDL instance")
        require_sha256(self.content_digest, "RAP Blocksworld task content_digest")
        if self.ground_truth_plan_length != 4:
            raise ValueError("RAP released step_4 cut requires four-step ground-truth plans")
        object.__setattr__(self, "pddl_path", normalized)

    @property
    def task_id(self) -> str:
        return f"blocksworld:{self.pddl_path.rsplit('/', 1)[-1]}"


def build_rap_blocksworld_step4_task_set(
    records: tuple[RapBlocksworldTaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    """Freeze the 57-task Blocksworld step_4 source cut released with RAP."""

    if type(records) is not tuple or any(type(row) is not RapBlocksworldTaskRecord for row in records):
        raise TypeError("RAP Blocksworld records must be RapBlocksworldTaskRecord")
    if len(records) != RAP_BLOCKSWORLD_STEP4_TASK_COUNT:
        raise ValueError("RAP Blocksworld step_4 cut requires exactly 57 tasks")
    require_sha256(source_digest, "RAP Blocksworld source_digest")
    ids = tuple(row.task_id for row in records)
    if len(ids) != len(set(ids)):
        raise ValueError("RAP Blocksworld task identities must be unique")

    tasks = tuple(
        sorted(
            (
                TaskDefinition(
                    task_id=row.task_id,
                    revision_id=RAP_BLOCKSWORLD_STEP4_REVISION,
                    family="blocksworld-step-4",
                    schema_id=RAP_BLOCKSWORLD_TASK_SCHEMA_ID,
                    content_digest=row.content_digest,
                    lineage_refs=(f"pddl:{row.pddl_path}",),
                )
                for row in records
            ),
            key=lambda row: row.task_id,
        )
    )
    return BenchmarkTaskSet(
        benchmark_id=RAP_BLOCKSWORLD_BENCHMARK_ID,
        revision_id=RAP_BLOCKSWORLD_STEP4_REVISION,
        source_digest=source_digest,
        task_schema_id=RAP_BLOCKSWORLD_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(TaskSetSplit(RAP_BLOCKSWORLD_STEP4_SPLIT, ids),),
        selection_policy_digest=RAP_BLOCKSWORLD_SELECTION_POLICY_DIGEST,
    )


__all__ = [
    "RAP_BLOCKSWORLD_BENCHMARK_ID",
    "RAP_BLOCKSWORLD_SELECTION_POLICY_DIGEST",
    "RAP_BLOCKSWORLD_STEP4_REVISION",
    "RAP_BLOCKSWORLD_STEP4_SPLIT",
    "RAP_BLOCKSWORLD_STEP4_TASK_COUNT",
    "RAP_BLOCKSWORLD_TASK_SCHEMA_ID",
    "RapBlocksworldTaskRecord",
    "build_rap_blocksworld_step4_task_set",
]
