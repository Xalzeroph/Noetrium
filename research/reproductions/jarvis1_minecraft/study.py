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
    StudyParticipant,
    TrialBudget,
)
from research.benchmarks.jarvis1_offline import (
    JARVIS1_ALL_SPLIT,
    JARVIS1_OFFLINE_BENCHMARK_ID,
    JARVIS1_OFFLINE_COMMIT,
    JARVIS1_TASK_COUNT,
    JARVIS1_TASKS_BLOB_SHA,
)

from .memory import JARVIS1_MEMORY_PROGRAM


JARVIS1_PUBLIC_DEFAULT_EVALUATION_MINUTES = 10
JARVIS1_PUBLIC_MAX_ENVIRONMENT_STEP = (
    1200 * JARVIS1_PUBLIC_DEFAULT_EVALUATION_MINUTES - 1
)


def jarvis1_tpami2025_public_offline_trial_protocol(
    benchmark: BenchmarkTaskSet,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != JARVIS1_OFFLINE_BENCHMARK_ID:
        raise ValueError(
            "JARVIS-1 public protocol requires official offline benchmark"
        )
    selected = benchmark.selected_tasks(JARVIS1_ALL_SPLIT)
    if len(selected) != JARVIS1_TASK_COUNT:
        raise ValueError("JARVIS-1 public protocol requires 185 source rows")
    return ExperimentTrialProtocolIdentity(
        "jarvis1.tpami2025.public-fixed-memory-offline.v1",
        canonical_digest({
            "source_commit": JARVIS1_OFFLINE_COMMIT,
            "tasks_blob_sha": JARVIS1_TASKS_BLOB_SHA,
            "benchmark_cut_digest": benchmark.cut_digest,
            "benchmark_split_id": JARVIS1_ALL_SPLIT,
            "task_ids": tuple(row.task_id for row in selected),
            "memory_program_digest": JARVIS1_MEMORY_PROGRAM.program_digest,
            "memory_mode": "official-fixed-task-keyed-memory",
            "multimodal_retrieval_mode": "unreleased-not-substituted",
            "online_learning_mode": "unreleased-not-substituted",
            "offline_evaluator": "offline_evaluation.py",
            "task_completion_monitor": (
                "jarvis.assembly.evaluate.monitor_function"
            ),
            "default_evaluation_minutes": (
                JARVIS1_PUBLIC_DEFAULT_EVALUATION_MINUTES
            ),
            "max_environment_step": JARVIS1_PUBLIC_MAX_ENVIRONMENT_STEP,
            "missing_plan_semantics": (
                "raise-NotImplementedError-online-planning-unreleased"
            ),
        }),
    )


def build_jarvis1_tpami2025_public_offline_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    protocol = jarvis1_tpami2025_public_offline_trial_protocol(benchmark)
    return Study(
        project_id="jarvis1-tpami-2025-reproduction",
        study_id="jarvis1-tpami-2025-public-fixed-memory-offline",
        benchmark=benchmark,
        benchmark_split_id=JARVIS1_ALL_SPLIT,
        method=StudyParticipant(
            role="minecraft_fixed_memory_planner",
            kind="method",
            implementation="jarvis1-public-memory",
            treatment="tpami-2025-public-fixed-memory-offline",
            capabilities=(
                "memory.retrieval",
                "environment.minecraft",
                "artifact.image.read",
            ),
            configurations=(
                "jarvis1.fixed-task-keyed-memory",
                "jarvis1.public-offline-only",
                "jarvis1.no-unreleased-retriever-substitution",
                "jarvis1.no-online-learning-substitution",
            ),
        ),
        models={},
        measurements=(
            MeasurementDefinition.scalar(
                "fixed_memory_hit",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="exact_task_key_memory_availability",
                scale="binary",
                domain="jarvis1_public_memory",
            ),
            MeasurementDefinition.scalar(
                "retrieved_plan_step_count",
                schema_id="noetrium.measurement.count.v1",
                unit="plan_step",
                semantic_kind="retrieved_fixed_memory_plan_size",
                scale="count",
                domain="jarvis1_public_memory",
            ),
            MeasurementDefinition.scalar(
                "offline_task_success",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="official_task_object_completion",
                scale="binary",
                domain="jarvis1_offline",
            ),
            MeasurementDefinition.scalar(
                "offline_environment_steps",
                schema_id="noetrium.measurement.count.v1",
                unit="environment_step",
                semantic_kind="minecraft_episode_length",
                scale="count",
                domain="jarvis1_offline",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("public-offline-environment-unpinned",),
        limits=TrialBudget(
            "jarvis1-tpami2025-public-offline-budget",
            max_steps=12000,
            max_turns=2048,
            max_model_calls=1,
            max_working_seconds=600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=600.0,
    ).build()


__all__ = [
    "JARVIS1_PUBLIC_DEFAULT_EVALUATION_MINUTES",
    "JARVIS1_PUBLIC_MAX_ENVIRONMENT_STEP",
    "build_jarvis1_tpami2025_public_offline_study",
    "jarvis1_tpami2025_public_offline_trial_protocol",
]
