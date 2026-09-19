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

M3TOOLEVAL_BENCHMARK_ID = "m3tooleval"
AGENTSQUARE_M3TOOL_SOURCE_COMMIT = "8f5b3fe5d8a32f9b59d20370823bef2a2c86928c"
AGENTSQUARE_M3TOOL_REVISION = f"agentsquare@{AGENTSQUARE_M3TOOL_SOURCE_COMMIT}:m3tool"
AGENTSQUARE_M3TOOL_SPLIT = "released_all_82"
AGENTSQUARE_M3TOOL_FAMILY_COUNTS = (
    ("travel_itinerary_planning", 15),
    ("message_decoder", 8),
    ("dna_sequencer", 8),
    ("trade_calculator", 17),
    ("web_browsing", 34),
)
AGENTSQUARE_M3TOOL_TASK_COUNT = sum(count for _, count in AGENTSQUARE_M3TOOL_FAMILY_COUNTS)
M3TOOLEVAL_TASK_SCHEMA_ID = "m3tooleval.task.v1"
AGENTSQUARE_M3TOOL_SELECTION_POLICY_DIGEST = canonical_digest({
    "source_commit": AGENTSQUARE_M3TOOL_SOURCE_COMMIT,
    "family_counts": AGENTSQUARE_M3TOOL_FAMILY_COUNTS,
    "action_mode": "text_as_action",
    "turn_limit": 10,
    "paper_metric": "success_rate",
})


@dataclass(frozen=True, slots=True)
class M3ToolTaskRecord:
    family: str
    task_name: str
    family_index: int
    content_digest: str

    def __post_init__(self) -> None:
        counts = dict(AGENTSQUARE_M3TOOL_FAMILY_COUNTS)
        if self.family not in counts:
            raise ValueError("M3Tool family is outside AgentSquare released cut")
        if type(self.family_index) is not int or not 0 <= self.family_index < counts[self.family]:
            raise ValueError("M3Tool family_index exceeds released family count")
        if type(self.task_name) is not str or not self.task_name.strip():
            raise ValueError("M3Tool task_name must be non-empty")
        require_sha256(self.content_digest, "M3Tool task content_digest")

    @property
    def task_id(self) -> str:
        return f"m3tool:{self.family}:{self.family_index:02d}:{self.task_name}"


def build_agentsquare_m3tool_task_set(
    records: tuple[M3ToolTaskRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or any(type(row) is not M3ToolTaskRecord for row in records):
        raise TypeError("M3Tool records must be a tuple of M3ToolTaskRecord")
    require_sha256(source_digest, "M3Tool source_digest")
    expected = {
        (family, index)
        for family, count in AGENTSQUARE_M3TOOL_FAMILY_COUNTS
        for index in range(count)
    }
    actual = {(row.family, row.family_index) for row in records}
    if len(records) != AGENTSQUARE_M3TOOL_TASK_COUNT or actual != expected:
        raise ValueError("AgentSquare M3Tool cut requires the exact 82 vendored tasks")
    ordered = tuple(sorted(records, key=lambda row: (row.family, row.family_index)))
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=AGENTSQUARE_M3TOOL_REVISION,
            family=row.family,
            schema_id=M3TOOLEVAL_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"family:{row.family}",
                f"family-index:{row.family_index}",
                f"task-name:{row.task_name}",
            ),
            package=TaskPackageSpec(
                package_schema_id="m3tooleval.tool-sandbox.v1",
                instruction_digest=row.content_digest,
                environment_requirement_id="benchmark.m3tooleval.tool-sandbox",
                verifier_requirement_id="benchmark.m3tooleval.answer.verifier",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for row in ordered
    )
    return BenchmarkTaskSet(
        benchmark_id=M3TOOLEVAL_BENCHMARK_ID,
        revision_id=AGENTSQUARE_M3TOOL_REVISION,
        source_digest=source_digest,
        task_schema_id=M3TOOLEVAL_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(TaskSetSplit(AGENTSQUARE_M3TOOL_SPLIT, tuple(row.task_id for row in ordered)),),
        selection_policy_digest=AGENTSQUARE_M3TOOL_SELECTION_POLICY_DIGEST,
    )


__all__ = [
    "AGENTSQUARE_M3TOOL_FAMILY_COUNTS",
    "AGENTSQUARE_M3TOOL_REVISION",
    "AGENTSQUARE_M3TOOL_SELECTION_POLICY_DIGEST",
    "AGENTSQUARE_M3TOOL_SOURCE_COMMIT",
    "AGENTSQUARE_M3TOOL_SPLIT",
    "AGENTSQUARE_M3TOOL_TASK_COUNT",
    "M3TOOLEVAL_BENCHMARK_ID",
    "M3TOOLEVAL_TASK_SCHEMA_ID",
    "M3ToolTaskRecord",
    "build_agentsquare_m3tool_task_set",
]
