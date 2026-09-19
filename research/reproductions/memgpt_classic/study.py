from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentTrialProtocolIdentity,
)
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    MeasurementDefinition,
    ReplayLevel,
    ResearchStudyDefinition,
    Study,
    StudyModel,
    StudyParticipant,
    TrialBudget,
)
from research.benchmarks.memoryarena import MEMORYARENA_BENCHMARK_ID

from .fidelity import MEMGPT_CLASSIC_FIDELITY
from .program import MEMGPT_CLASSIC_METHOD_PROGRAM

MEMGPT_MEMORYARENA_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "memgpt.classic.memoryarena.v1",
    canonical_digest(
        {
            "program_digest": MEMGPT_CLASSIC_METHOD_PROGRAM.program_digest,
            "paper_era_anchor": MEMGPT_CLASSIC_FIDELITY.audited_anchor_commit,
            "recall_page_size": MEMGPT_CLASSIC_FIDELITY.recall_default_page_size,
            "archival_page_size": MEMGPT_CLASSIC_FIDELITY.archival_default_page_size,
            "overflow_strategy": MEMGPT_CLASSIC_FIDELITY.overflow_strategy,
            "summary_fraction": MEMGPT_CLASSIC_FIDELITY.default_summary_fraction,
        }
    ),
)


def build_memgpt_memoryarena_study(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ResearchStudyDefinition:
    """Build a native pressure-study protocol for classic MemGPT on MemoryArena."""

    if benchmark.benchmark_id != MEMORYARENA_BENCHMARK_ID:
        raise ValueError("classic MemGPT MemoryArena study requires MemoryArena")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("classic MemGPT MemoryArena study requires a non-empty split")

    return Study(
        project_id="memgpt-classic-reproduction",
        study_id=f"memgpt-classic-memoryarena-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="agent",
            kind="agent",
            implementation="memgpt-classic",
            treatment="paper-era-memory-semantics",
            capabilities=(
                "memory.recall.query",
                "memory.archival.query",
                "memory.archival.insert",
            ),
            configurations=("memgpt.classic.prompt",),
        ),
        models={
            "agent": StudyModel(
                "model.memgpt.agent",
                prompt="memgpt.classic.prompt",
            ),
            "summarizer": StudyModel(
                "model.memgpt.summarizer",
                prompt="memgpt.classic.summary",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="memoryarena",
            ),
            MeasurementDefinition.scalar(
                "agent_turn_count",
                schema_id="noetrium.measurement.count.v1",
                unit="turn",
                semantic_kind="resource_usage",
                scale="count",
                domain="memoryarena",
            ),
            MeasurementDefinition.scalar(
                "memory_query_count",
                schema_id="noetrium.measurement.count.v1",
                unit="query",
                semantic_kind="memory_usage",
                scale="count",
                domain="memoryarena",
            ),
            MeasurementDefinition.scalar(
                "memory_write_count",
                schema_id="noetrium.measurement.count.v1",
                unit="write",
                semantic_kind="memory_usage",
                scale="count",
                domain="memoryarena",
            ),
            MeasurementDefinition.scalar(
                "summary_count",
                schema_id="noetrium.measurement.count.v1",
                unit="summary",
                semantic_kind="context_management",
                scale="count",
                domain="memoryarena",
            ),
        ),
        trial=MEMGPT_MEMORYARENA_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=("0",),
        limits=TrialBudget(
            "memgpt-classic-memoryarena-budget",
            max_steps=1024,
            max_turns=128,
            max_model_calls=160,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "MEMGPT_MEMORYARENA_TRIAL_PROTOCOL",
    "build_memgpt_memoryarena_study",
]
