from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkSourceKind,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskDefinition,
    TaskPackageSpec,
    TaskSetSplit,
    TaskVerifierIsolation,
)

GENERATIVE_AGENTS_BENCHMARK_ID = "generative-agents-smallville"
GENERATIVE_AGENTS_SPLIT_ID = "paper-smallville"
GENERATIVE_AGENTS_PAPER_COMMIT = "fe05a71d3e4ed7d10bf68aa4eda6dd995ec070f4"
GENERATIVE_AGENTS_PROTOCOL_DIGEST = canonical_digest({
    "paper": "Generative Agents UIST 2023",
    "source_commit": GENERATIVE_AGENTS_PAPER_COMMIT,
    "population_size": 25,
    "architecture_components": ("observation", "planning", "reflection"),
    "evaluation": "believability plus architecture ablations",
    "sandbox": "Smallville",
})


def build_generative_agents_smallville_source() -> BenchmarkSourceSpec:
    return BenchmarkSourceSpec(
        source_id=GENERATIVE_AGENTS_BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=f"uist2023@{GENERATIVE_AGENTS_PAPER_COMMIT}",
        locator="https://github.com/joonspk-research/generative_agents",
        content_digest=GENERATIVE_AGENTS_PROTOCOL_DIGEST,
        metadata={
            "paper_venue": "UIST 2023",
            "population_size": "25",
            "evaluation_kind": "human-believability-and-ablation",
        },
    )


def build_generative_agents_smallville_cut() -> BenchmarkTaskSet:
    revision = f"uist2023@{GENERATIVE_AGENTS_PAPER_COMMIT}"
    task = TaskDefinition(
        task_id="generative-agents:smallville:paper-simulation",
        revision_id=revision,
        family="smallville_social_simulation",
        schema_id="generative-agents.smallville-simulation.v1",
        content_digest=GENERATIVE_AGENTS_PROTOCOL_DIGEST,
        lineage_refs=(
            "population:25",
            "architecture:observation+planning+reflection",
            "evaluation:believability",
        ),
        package=TaskPackageSpec(
            package_schema_id="generative-agents.smallville-package.v1",
            instruction_digest=canonical_digest({
                "objective": "run the paper-era Smallville social simulation protocol",
                "population_size": 25,
            }),
            environment_requirement_id="environment.social-simulation.smallville-paper-era",
            verifier_requirement_id="benchmark.generative-agents.believability",
            verifier_isolation=TaskVerifierIsolation.SEPARATE,
        ),
    )
    return BenchmarkTaskSet(
        benchmark_id=GENERATIVE_AGENTS_BENCHMARK_ID,
        revision_id=revision,
        source_digest=GENERATIVE_AGENTS_PROTOCOL_DIGEST,
        task_schema_id="generative-agents.smallville-simulation.v1",
        tasks=(task,),
        splits=(
            TaskSetSplit("all", (task.task_id,)),
            TaskSetSplit(GENERATIVE_AGENTS_SPLIT_ID, (task.task_id,)),
        ),
        selection_policy_digest=canonical_digest({
            "protocol_digest": GENERATIVE_AGENTS_PROTOCOL_DIGEST,
            "task_ids": (task.task_id,),
        }),
    )


__all__ = [
    "GENERATIVE_AGENTS_BENCHMARK_ID",
    "GENERATIVE_AGENTS_PAPER_COMMIT",
    "GENERATIVE_AGENTS_PROTOCOL_DIGEST",
    "GENERATIVE_AGENTS_SPLIT_ID",
    "build_generative_agents_smallville_cut",
    "build_generative_agents_smallville_source",
]
