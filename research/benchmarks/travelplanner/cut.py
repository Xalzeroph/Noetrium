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

TRAVELPLANNER_BENCHMARK_ID = "travelplanner"
AGENTSQUARE_TRAVELPLANNER_SOURCE_COMMIT = "8f5b3fe5d8a32f9b59d20370823bef2a2c86928c"
AGENTSQUARE_TRAVELPLANNER_DATASET_REVISION = "8736504ecfc31b7f8b7e40122873c337e83fff7c"
AGENTSQUARE_TRAVELPLANNER_REVISION = (
    f"agentsquare@{AGENTSQUARE_TRAVELPLANNER_SOURCE_COMMIT}:"
    f"travelplanner@{AGENTSQUARE_TRAVELPLANNER_DATASET_REVISION}"
)
AGENTSQUARE_TRAVELPLANNER_FULL_VALIDATION_SPLIT = "validation_180"
AGENTSQUARE_TRAVELPLANNER_EVALUATION_SPLIT = "released_eval_validation_150_179"
AGENTSQUARE_TRAVELPLANNER_SEARCH_SPLIT = "released_search_first_30"
AGENTSQUARE_TRAVELPLANNER_VALIDATION_COUNT = 180
AGENTSQUARE_TRAVELPLANNER_EVALUATION_START = 150
AGENTSQUARE_TRAVELPLANNER_EVALUATION_END = 180
AGENTSQUARE_TRAVELPLANNER_EVALUATION_COUNT = (
    AGENTSQUARE_TRAVELPLANNER_EVALUATION_END
    - AGENTSQUARE_TRAVELPLANNER_EVALUATION_START
)
AGENTSQUARE_TRAVELPLANNER_SEARCH_COUNT = 30
TRAVELPLANNER_TASK_SCHEMA_ID = "travelplanner.query.v1"
AGENTSQUARE_TRAVELPLANNER_SELECTION_POLICY_DIGEST = canonical_digest({
    "source_commit": AGENTSQUARE_TRAVELPLANNER_SOURCE_COMMIT,
    "dataset_revision": AGENTSQUARE_TRAVELPLANNER_DATASET_REVISION,
    "validation_count": AGENTSQUARE_TRAVELPLANNER_VALIDATION_COUNT,
    "search_count": AGENTSQUARE_TRAVELPLANNER_SEARCH_COUNT,
    "search_selection": "first-30-missing-file-order",
    "evaluation_start": AGENTSQUARE_TRAVELPLANNER_EVALUATION_START,
    "evaluation_end_exclusive": AGENTSQUARE_TRAVELPLANNER_EVALUATION_END,
    "evaluation_selection": "released-evaluator-validation-slice-150-180",
    "evaluation_metric": "commonsense_constraint_micro_pass_rate",
})


@dataclass(frozen=True, slots=True)
class TravelPlannerTaskRecord:
    index: int
    query: str
    level: str
    content_digest: str

    def __post_init__(self) -> None:
        if type(self.index) is not int or not 0 <= self.index < AGENTSQUARE_TRAVELPLANNER_VALIDATION_COUNT:
            raise ValueError("TravelPlanner validation index must be in [0, 180)")
        if type(self.query) is not str or not self.query.strip():
            raise ValueError("TravelPlanner query must be non-empty")
        if type(self.level) is not str or not self.level.strip():
            raise ValueError("TravelPlanner level must be non-empty")
        require_sha256(self.content_digest, "TravelPlanner task content_digest")

    @property
    def task_id(self) -> str:
        return f"travelplanner:validation:{self.index + 1:03d}"


def build_agentsquare_travelplanner_task_set(
    records: tuple[TravelPlannerTaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or any(type(row) is not TravelPlannerTaskRecord for row in records):
        raise TypeError("TravelPlanner records must be a tuple of TravelPlannerTaskRecord")
    require_sha256(source_digest, "TravelPlanner source_digest")
    if len(records) != AGENTSQUARE_TRAVELPLANNER_VALIDATION_COUNT:
        raise ValueError("TravelPlanner validation cut requires exactly 180 tasks")
    by_index = {row.index: row for row in records}
    if set(by_index) != set(range(AGENTSQUARE_TRAVELPLANNER_VALIDATION_COUNT)):
        raise ValueError("TravelPlanner cut requires canonical validation indices 0 through 179")
    ordered = tuple(by_index[index] for index in range(AGENTSQUARE_TRAVELPLANNER_VALIDATION_COUNT))
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=AGENTSQUARE_TRAVELPLANNER_REVISION,
            family=row.level,
            schema_id=TRAVELPLANNER_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"validation-index:{row.index}",
                f"level:{row.level}",
            ),
            package=TaskPackageSpec(
                package_schema_id="travelplanner.execution-package.v1",
                instruction_digest=row.content_digest,
                environment_requirement_id="benchmark.travelplanner.tool-sandbox",
                verifier_requirement_id="benchmark.travelplanner.constraints.verifier",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for row in ordered
    )
    all_ids = tuple(row.task_id for row in ordered)
    search_ids = all_ids[:AGENTSQUARE_TRAVELPLANNER_SEARCH_COUNT]
    evaluation_ids = all_ids[
        AGENTSQUARE_TRAVELPLANNER_EVALUATION_START:
        AGENTSQUARE_TRAVELPLANNER_EVALUATION_END
    ]
    return BenchmarkTaskSet(
        benchmark_id=TRAVELPLANNER_BENCHMARK_ID,
        revision_id=AGENTSQUARE_TRAVELPLANNER_REVISION,
        source_digest=source_digest,
        task_schema_id=TRAVELPLANNER_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(
            TaskSetSplit(
                AGENTSQUARE_TRAVELPLANNER_FULL_VALIDATION_SPLIT,
                all_ids,
            ),
            TaskSetSplit(AGENTSQUARE_TRAVELPLANNER_SEARCH_SPLIT, search_ids),
            TaskSetSplit(
                AGENTSQUARE_TRAVELPLANNER_EVALUATION_SPLIT,
                evaluation_ids,
            ),
        ),
        selection_policy_digest=AGENTSQUARE_TRAVELPLANNER_SELECTION_POLICY_DIGEST,
    )


__all__ = [
    "AGENTSQUARE_TRAVELPLANNER_DATASET_REVISION",
    "AGENTSQUARE_TRAVELPLANNER_REVISION",
    "AGENTSQUARE_TRAVELPLANNER_EVALUATION_COUNT",
    "AGENTSQUARE_TRAVELPLANNER_EVALUATION_END",
    "AGENTSQUARE_TRAVELPLANNER_EVALUATION_SPLIT",
    "AGENTSQUARE_TRAVELPLANNER_EVALUATION_START",
    "AGENTSQUARE_TRAVELPLANNER_FULL_VALIDATION_SPLIT",
    "AGENTSQUARE_TRAVELPLANNER_SEARCH_COUNT",
    "AGENTSQUARE_TRAVELPLANNER_SEARCH_SPLIT",
    "AGENTSQUARE_TRAVELPLANNER_SELECTION_POLICY_DIGEST",
    "AGENTSQUARE_TRAVELPLANNER_SOURCE_COMMIT",
    "AGENTSQUARE_TRAVELPLANNER_VALIDATION_COUNT",
    "TRAVELPLANNER_BENCHMARK_ID",
    "TRAVELPLANNER_TASK_SCHEMA_ID",
    "TravelPlannerTaskRecord",
    "build_agentsquare_travelplanner_task_set",
]
