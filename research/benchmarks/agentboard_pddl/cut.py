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

AGENTBOARD_PDDL_BENCHMARK_ID = "agentboard-pddl"
AGENTSQUARE_PDDL_SOURCE_COMMIT = "8f5b3fe5d8a32f9b59d20370823bef2a2c86928c"
AGENTSQUARE_PDDL_REVISION = f"agentsquare@{AGENTSQUARE_PDDL_SOURCE_COMMIT}:agentboard-pddl"
AGENTSQUARE_PDDL_SPLIT = "released_eval_60"
AGENTSQUARE_PDDL_DOMAIN_COUNTS = (
    ("barman", 20),
    ("blockworld", 10),
    ("gripper", 20),
    ("tyreworld", 10),
)
AGENTSQUARE_PDDL_TASK_COUNT = sum(count for _, count in AGENTSQUARE_PDDL_DOMAIN_COUNTS)
AGENTBOARD_PDDL_TASK_SCHEMA_ID = "agentboard.pddl-task.v1"
AGENTSQUARE_PDDL_SELECTION_POLICY_DIGEST = canonical_digest({
    "source_commit": AGENTSQUARE_PDDL_SOURCE_COMMIT,
    "domain_counts": AGENTSQUARE_PDDL_DOMAIN_COUNTS,
    "selection": "min(env_num_per_task=20, released-domain-cap)",
    "paper_metric": "progress_rate",
})


@dataclass(frozen=True, slots=True)
class AgentBoardPddlTaskRecord:
    domain: str
    problem_index: int
    difficulty: str
    content_digest: str

    def __post_init__(self) -> None:
        caps = dict(AGENTSQUARE_PDDL_DOMAIN_COUNTS)
        if self.domain not in caps:
            raise ValueError("AgentBoard PDDL domain is not in released four-domain cut")
        if type(self.problem_index) is not int or not 0 <= self.problem_index < caps[self.domain]:
            raise ValueError("AgentBoard PDDL problem_index exceeds released domain cap")
        if type(self.difficulty) is not str or not self.difficulty.strip():
            raise ValueError("AgentBoard PDDL difficulty must be non-empty")
        require_sha256(self.content_digest, "AgentBoard PDDL task content_digest")

    @property
    def task_id(self) -> str:
        return f"agentboard-pddl:{self.domain}:{self.problem_index:02d}"


def build_agentsquare_pddl_task_set(
    records: tuple[AgentBoardPddlTaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or any(type(row) is not AgentBoardPddlTaskRecord for row in records):
        raise TypeError("PDDL records must be a tuple of AgentBoardPddlTaskRecord")
    require_sha256(source_digest, "AgentBoard PDDL source_digest")
    expected = {
        (domain, index)
        for domain, count in AGENTSQUARE_PDDL_DOMAIN_COUNTS
        for index in range(count)
    }
    actual = {(row.domain, row.problem_index) for row in records}
    if len(records) != AGENTSQUARE_PDDL_TASK_COUNT or actual != expected:
        raise ValueError("AgentSquare PDDL cut requires the exact released 60 problems")
    ordered = tuple(sorted(records, key=lambda row: (row.domain, row.problem_index)))
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=AGENTSQUARE_PDDL_REVISION,
            family=row.domain,
            schema_id=AGENTBOARD_PDDL_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"domain:{row.domain}",
                f"problem-index:{row.problem_index}",
                f"difficulty:{row.difficulty}",
            ),
            package=TaskPackageSpec(
                package_schema_id="agentboard.pddl-execution.v1",
                instruction_digest=row.content_digest,
                environment_requirement_id="benchmark.agentboard.pddl.environment",
                verifier_requirement_id="benchmark.agentboard.progress.verifier",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for row in ordered
    )
    return BenchmarkTaskSet(
        benchmark_id=AGENTBOARD_PDDL_BENCHMARK_ID,
        revision_id=AGENTSQUARE_PDDL_REVISION,
        source_digest=source_digest,
        task_schema_id=AGENTBOARD_PDDL_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(TaskSetSplit(AGENTSQUARE_PDDL_SPLIT, tuple(row.task_id for row in ordered)),),
        selection_policy_digest=AGENTSQUARE_PDDL_SELECTION_POLICY_DIGEST,
    )


__all__ = [
    "AGENTBOARD_PDDL_BENCHMARK_ID",
    "AGENTBOARD_PDDL_TASK_SCHEMA_ID",
    "AGENTSQUARE_PDDL_DOMAIN_COUNTS",
    "AGENTSQUARE_PDDL_REVISION",
    "AGENTSQUARE_PDDL_SELECTION_POLICY_DIGEST",
    "AGENTSQUARE_PDDL_SOURCE_COMMIT",
    "AGENTSQUARE_PDDL_SPLIT",
    "AGENTSQUARE_PDDL_TASK_COUNT",
    "AgentBoardPddlTaskRecord",
    "build_agentsquare_pddl_task_set",
]
