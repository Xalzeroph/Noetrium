from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.lifecycle.api import (
    ExperimentTrialProtocolIdentity,
)
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkTaskSet,
    MeasurementDefinition,
    ReplayLevel,
    ResearchStudyDefinition,
    Study,
    StudyModel,
    StudyParticipant,
    TrialBudget,
)
from research.benchmarks.minecraft_long_horizon_67 import (
    MINECRAFT_LONG_HORIZON_67_ALL_SPLIT,
    MINECRAFT_LONG_HORIZON_67_BENCHMARK_ID,
    MINECRAFT_LONG_HORIZON_67_GROUP_MAX_STEPS,
    MINECRAFT_LONG_HORIZON_67_PROTOCOL_DIGEST,
    MINECRAFT_LONG_HORIZON_67_TASK_COUNT,
)

from .program import OPTIMUS2_METHOD_PROGRAM
from .source import OPTIMUS2_PAPER_REPOSITORY_COMMIT


def optimus2_cvpr2025_long_horizon_trial_protocol(
    benchmark: BenchmarkTaskSet,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != MINECRAFT_LONG_HORIZON_67_BENCHMARK_ID:
        raise ValueError("Optimus-2 study requires Minecraft Long-Horizon 67")
    selected = benchmark.selected_tasks(MINECRAFT_LONG_HORIZON_67_ALL_SPLIT)
    if len(selected) != MINECRAFT_LONG_HORIZON_67_TASK_COUNT:
        raise ValueError("Optimus-2 study requires the 67-task long-horizon cut")
    return ExperimentTrialProtocolIdentity(
        "optimus2.cvpr2025.minecraft-long-horizon-67.v1",
        canonical_digest(
            {
                "paper_repository_commit": OPTIMUS2_PAPER_REPOSITORY_COMMIT,
                "method_program_digest": OPTIMUS2_METHOD_PROGRAM.program_digest,
                "benchmark_cut_digest": benchmark.cut_digest,
                "benchmark_protocol_digest": (
                    MINECRAFT_LONG_HORIZON_67_PROTOCOL_DIGEST
                ),
                "benchmark_split_id": MINECRAFT_LONG_HORIZON_67_ALL_SPLIT,
                "task_ids": tuple(row.task_id for row in selected),
                "group_max_environment_steps": (
                    MINECRAFT_LONG_HORIZON_67_GROUP_MAX_STEPS
                ),
                "evaluation_scope": "long_horizon_tasks",
                "metric": "average_success_rate",
                "initial_inventory": (),
                "planner": "multimodal-large-language-model",
                "controller": "goal-observation-action-conditioned-policy",
                "exact_model_artifacts": "unreleased",
            }
        ),
    )


def build_optimus2_cvpr2025_long_horizon_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    protocol = optimus2_cvpr2025_long_horizon_trial_protocol(benchmark)
    return Study(
        project_id="optimus2-cvpr-2025-reproduction",
        study_id="optimus2-cvpr-2025-minecraft-long-horizon-67",
        benchmark=benchmark,
        benchmark_split_id=MINECRAFT_LONG_HORIZON_67_ALL_SPLIT,
        method=StudyParticipant(
            role="goal_observation_action_minecraft_agent",
            kind="agent_method",
            implementation="optimus2",
            treatment="cvpr-2025-paper-described-independent-reconstruction",
            capabilities=(
                "environment.minecraft",
                "model.multimodal.generate",
            ),
            configurations=(
                "optimus2.mllm-planner",
                "optimus2.goap-policy",
                "optimus2.action-guided-behavior-encoder",
                "optimus2.history-aggregator",
                "optimus2.memory-bank",
            ),
        ),
        models={
            "planner": StudyModel(
                "model.optimus2.mllm-paper-described-unreleased",
                prompt="optimus2.high-level-planning",
            ),
            "controller": StudyModel(
                "model.optimus2.goap-paper-described-unreleased",
                prompt="optimus2.goal-observation-action-policy",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="minecraft_goal_success",
                scale="binary",
                domain="minecraft_long_horizon_67",
            ),
            MeasurementDefinition.scalar(
                "environment_steps",
                schema_id="noetrium.measurement.count.v1",
                unit="environment_step",
                semantic_kind="minecraft_episode_length",
                scale="count",
                domain="minecraft_long_horizon_67",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("paper-world-seed-unpublished",),
        limits=TrialBudget(
            "optimus2-cvpr2025-long-horizon-67-safety",
            max_steps=36000,
            max_turns=4096,
            max_model_calls=4096,
            max_working_seconds=1800.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=1800.0,
    ).build()


__all__ = [
    "build_optimus2_cvpr2025_long_horizon_study",
    "optimus2_cvpr2025_long_horizon_trial_protocol",
]
