from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest
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

FLOW_PRACTICAL_BENCHMARK_ID = "flow-practical-tasks"
FLOW_PRACTICAL_SPLIT_ID = "iclr2025-three-designed-tasks"
FLOW_PAPER_URI = (
    "https://proceedings.iclr.cc/paper_files/paper/2025/hash/"
    "ba84da6921f3040b74ee163aa7451f53-Abstract-Conference.html"
)

_FLOW_TASKS = (
    (
        "gobang-game-development",
        "software",
        (
            "Create a Gobang game with a user interface and a simple AI opponent. "
            "Players can choose black or white stones; the interface must clearly "
            "indicate turns and announce a winner or draw."
        ),
        ("compilable", "basic_game", "ai_opponent", "user_interface"),
    ),
    (
        "latex-beamer-writing",
        "document",
        (
            "Generate LaTeX Beamer slides covering reinforcement-learning "
            "algorithms, including motivation, problem statements, intuitive "
            "solutions, and detailed mathematical equations, while satisfying "
            "the paper's page requirement."
        ),
        ("compilable", "content_coverage", "mathematical_detail", "page_requirement"),
    ),
    (
        "website-design",
        "software",
        (
            "Build a professional website for a hypothetical ICLR conference in "
            "San Francisco from April 27 to May 1, 2025, including a detailed "
            "conference schedule, venue information, and an interactive map."
        ),
        ("compilable", "basic_information", "sections"),
    ),
)

FLOW_PRACTICAL_PROTOCOL_DIGEST = canonical_digest({
    "paper": "Flow ICLR 2025",
    "paper_uri": FLOW_PAPER_URI,
    "tasks": _FLOW_TASKS,
    "evaluation": {
        "quantitative": "task-specific success-rate criteria",
        "qualitative": "human rating on a 1-4 scale",
        "human_participants": 50,
    },
})


@dataclass(frozen=True, slots=True, order=True)
class FlowPracticalTaskRecord:
    task_id: str
    family: str
    instruction: str
    success_criteria: tuple[str, ...]

    @property
    def content_digest(self) -> str:
        return canonical_digest({
            "task_id": self.task_id,
            "family": self.family,
            "instruction": self.instruction,
            "success_criteria": self.success_criteria,
        })


FLOW_PRACTICAL_TASKS = tuple(
    FlowPracticalTaskRecord(*row) for row in _FLOW_TASKS
)


def build_flow_practical_source() -> BenchmarkSourceSpec:
    return BenchmarkSourceSpec(
        source_id=FLOW_PRACTICAL_BENCHMARK_ID,
        kind=BenchmarkSourceKind.CUSTOM,
        revision_id="flow:iclr2025:paper-designed-tasks",
        locator=FLOW_PAPER_URI,
        content_digest=FLOW_PRACTICAL_PROTOCOL_DIGEST,
        metadata={
            "paper_venue": "ICLR 2025",
            "task_count": "3",
            "human_rater_count": "50",
            "human_rating_scale": "1-4",
        },
    )


def build_flow_practical_task_set() -> BenchmarkTaskSet:
    revision = "flow:iclr2025:paper-designed-tasks"
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=revision,
            family=row.family,
            schema_id="flow.practical-task.v1",
            content_digest=row.content_digest,
            lineage_refs=(
                f"paper-task:{row.task_id}",
                *tuple(f"success-criterion:{item}" for item in row.success_criteria),
            ),
            package=TaskPackageSpec(
                package_schema_id="flow.practical-task-package.v1",
                instruction_digest=canonical_digest(row.instruction),
                environment_requirement_id=(
                    "environment.software.flow-paper-task"
                    if row.family == "software"
                    else "environment.document.flow-paper-task"
                ),
                verifier_requirement_id=f"benchmark.flow.{row.task_id}.verifier",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
                artifacts=(
                    TaskArtifactSpec("flow_output", "output/", True),
                    TaskArtifactSpec("flow_trace", "workflow.json", True),
                ),
            ),
        )
        for row in FLOW_PRACTICAL_TASKS
    )
    ids = tuple(row.task_id for row in tasks)
    return BenchmarkTaskSet(
        benchmark_id=FLOW_PRACTICAL_BENCHMARK_ID,
        revision_id=revision,
        source_digest=FLOW_PRACTICAL_PROTOCOL_DIGEST,
        task_schema_id="flow.practical-task.v1",
        tasks=tasks,
        splits=(
            TaskSetSplit("all", ids),
            TaskSetSplit(FLOW_PRACTICAL_SPLIT_ID, ids),
        ),
        selection_policy_digest=canonical_digest({
            "protocol_digest": FLOW_PRACTICAL_PROTOCOL_DIGEST,
            "task_ids": ids,
            "selection": "all_three_paper_designed_tasks",
        }),
    )


__all__ = [
    "FLOW_PAPER_URI",
    "FLOW_PRACTICAL_BENCHMARK_ID",
    "FLOW_PRACTICAL_PROTOCOL_DIGEST",
    "FLOW_PRACTICAL_SPLIT_ID",
    "FLOW_PRACTICAL_TASKS",
    "FlowPracticalTaskRecord",
    "build_flow_practical_source",
    "build_flow_practical_task_set",
]
