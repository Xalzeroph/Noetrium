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

SCIENCEWORLD_BENCHMARK_ID = "scienceworld"
AGENTSQUARE_SCIENCEWORLD_SOURCE_COMMIT = "8f5b3fe5d8a32f9b59d20370823bef2a2c86928c"
AGENTSQUARE_SCIENCEWORLD_REVISION = (
    f"agentsquare@{AGENTSQUARE_SCIENCEWORLD_SOURCE_COMMIT}:agentboard-scienceworld"
)
AGENTSQUARE_SCIENCEWORLD_SPLIT = "agentboard_eval_90"
AGENTSQUARE_SCIENCEWORLD_TASK_COUNT = 90
SCIENCEWORLD_TASK_SCHEMA_ID = "scienceworld.agentboard-task.v1"
AGENTSQUARE_SCIENCEWORLD_SELECTION_POLICY_DIGEST = canonical_digest({
    "source_commit": AGENTSQUARE_SCIENCEWORLD_SOURCE_COMMIT,
    "task_count": AGENTSQUARE_SCIENCEWORLD_TASK_COUNT,
    "selection": "released_agentboard_label_order",
    "max_environment_steps": 30,
    "paper_metric": "progress_rate",
})


@dataclass(frozen=True, slots=True)
class ScienceWorldTaskRecord:
    index: int
    task_name: str
    variation: int
    content_digest: str

    def __post_init__(self) -> None:
        if type(self.index) is not int or not 0 <= self.index < AGENTSQUARE_SCIENCEWORLD_TASK_COUNT:
            raise ValueError("ScienceWorld index must be in [0, 90)")
        if type(self.task_name) is not str or not self.task_name.strip():
            raise ValueError("ScienceWorld task_name must be non-empty")
        if type(self.variation) is not int or self.variation < 0:
            raise ValueError("ScienceWorld variation must be non-negative")
        require_sha256(self.content_digest, "ScienceWorld task content_digest")

    @property
    def task_id(self) -> str:
        return f"scienceworld:{self.index:03d}:{self.task_name}:v{self.variation}"


def build_agentsquare_scienceworld_task_set(
    records: tuple[ScienceWorldTaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or any(type(row) is not ScienceWorldTaskRecord for row in records):
        raise TypeError("ScienceWorld records must be a tuple of ScienceWorldTaskRecord")
    require_sha256(source_digest, "ScienceWorld source_digest")
    if len(records) != AGENTSQUARE_SCIENCEWORLD_TASK_COUNT:
        raise ValueError("AgentSquare ScienceWorld cut requires exactly 90 tasks")
    by_index = {row.index: row for row in records}
    if set(by_index) != set(range(AGENTSQUARE_SCIENCEWORLD_TASK_COUNT)):
        raise ValueError("ScienceWorld cut requires canonical indices 0 through 89")
    ordered = tuple(by_index[index] for index in range(AGENTSQUARE_SCIENCEWORLD_TASK_COUNT))
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=AGENTSQUARE_SCIENCEWORLD_REVISION,
            family="scienceworld",
            schema_id=SCIENCEWORLD_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"source-index:{row.index}",
                f"scienceworld-task:{row.task_name}",
                f"variation:{row.variation}",
            ),
            package=TaskPackageSpec(
                package_schema_id="scienceworld.agentboard-execution.v1",
                instruction_digest=row.content_digest,
                environment_requirement_id="benchmark.scienceworld.environment",
                verifier_requirement_id="benchmark.agentboard.progress.verifier",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for row in ordered
    )
    return BenchmarkTaskSet(
        benchmark_id=SCIENCEWORLD_BENCHMARK_ID,
        revision_id=AGENTSQUARE_SCIENCEWORLD_REVISION,
        source_digest=source_digest,
        task_schema_id=SCIENCEWORLD_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(TaskSetSplit(AGENTSQUARE_SCIENCEWORLD_SPLIT, tuple(row.task_id for row in ordered)),),
        selection_policy_digest=AGENTSQUARE_SCIENCEWORLD_SELECTION_POLICY_DIGEST,
    )


__all__ = [
    "AGENTSQUARE_SCIENCEWORLD_REVISION",
    "AGENTSQUARE_SCIENCEWORLD_SELECTION_POLICY_DIGEST",
    "AGENTSQUARE_SCIENCEWORLD_SOURCE_COMMIT",
    "AGENTSQUARE_SCIENCEWORLD_SPLIT",
    "AGENTSQUARE_SCIENCEWORLD_TASK_COUNT",
    "SCIENCEWORLD_BENCHMARK_ID",
    "SCIENCEWORLD_TASK_SCHEMA_ID",
    "ScienceWorldTaskRecord",
    "build_agentsquare_scienceworld_task_set",
]
