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

from .benchmark import MINEDOJO_ALL_SPLIT, MINEDOJO_BENCHMARK_ID
from .fidelity import MINEDOJO_REFERENCE_FIDELITY
from .program import MINEAGENT_METHOD_PROGRAM
from .source import MINECLIP_AUDITED_COMMIT, MINEDOJO_AUDITED_COMMIT


def minedojo_neurips2022_trial_protocol(
    benchmark: BenchmarkTaskSet,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != MINEDOJO_BENCHMARK_ID:
        raise ValueError(
            "MineDojo protocol requires canonical MineDojo benchmark"
        )
    selected = benchmark.selected_tasks(MINEDOJO_ALL_SPLIT)
    expected = MINEDOJO_REFERENCE_FIDELITY.benchmark_task_count
    if len(selected) != expected:
        raise ValueError(
            f"MineDojo protocol requires exactly {expected} tasks"
        )
    return ExperimentTrialProtocolIdentity(
        "minedojo.neurips2022.mineagent.v1",
        canonical_digest({
            "benchmark_source_commit": MINEDOJO_AUDITED_COMMIT,
            "mineclip_source_commit": MINECLIP_AUDITED_COMMIT,
            "benchmark_cut_digest": benchmark.cut_digest,
            "benchmark_split_id": MINEDOJO_ALL_SPLIT,
            "task_count": len(selected),
            "method_program_digest": MINEAGENT_METHOD_PROGRAM.program_digest,
            "deterministic_eval": (
                MINEDOJO_REFERENCE_FIDELITY
                .mineagent_deterministic_eval_uses_mode
            ),
            "actor_action_dims": (
                MINEDOJO_REFERENCE_FIDELITY.mineagent_actor_action_dims
            ),
            "demo_action_projection": {
                "environment_dims": (
                    MINEDOJO_REFERENCE_FIDELITY
                    .mineagent_demo_environment_action_dims
                ),
                "force_sixth_zero": (
                    MINEDOJO_REFERENCE_FIDELITY
                    .mineagent_demo_forces_sixth_action_zero
                ),
                "append_suffix": (
                    MINEDOJO_REFERENCE_FIDELITY
                    .mineagent_demo_appends_action_suffix
                ),
            },
            "reward_semantics": "MineCLIP video-text similarity",
            "programmatic_success_aggregation": (
                MINEDOJO_REFERENCE_FIDELITY
                .programmatic_success_aggregation
            ),
        }),
    )


def build_minedojo_neurips2022_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    protocol = minedojo_neurips2022_trial_protocol(benchmark)
    return Study(
        project_id="minedojo-neurips-2022-reproduction",
        study_id="minedojo-neurips-2022-mineagent",
        benchmark=benchmark,
        benchmark_split_id=MINEDOJO_ALL_SPLIT,
        method=StudyParticipant(
            role="language_conditioned_minecraft_policy",
            kind="method",
            implementation="mineagent",
            treatment="neurips-2022-paper-release",
            capabilities=(
                "environment.minecraft",
                "model.mineagent.policy",
                "model.mineclip.reward",
                "artifact.tensor.read",
                "artifact.tensor.write",
            ),
            configurations=(
                "mineagent.deterministic-mode-eval",
                "mineagent.multidiscrete-3x3x4x25x25x8",
                "mineclip.temporal-window-32",
                "minedojo.programmatic-success-any",
            ),
        ),
        models={
            "policy": StudyModel(
                "model.mineagent.paper-release",
                prompt="minedojo.language-prompt",
            ),
            "reward": StudyModel(
                "model.mineclip.attn.paper-release",
                prompt="minedojo.language-prompt",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "episode_success",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="minecraft_task_success",
                scale="binary",
                domain="minedojo",
            ),
            MeasurementDefinition.scalar(
                "episode_steps",
                schema_id="noetrium.measurement.count.v1",
                unit="environment_step",
                semantic_kind="minecraft_episode_length",
                scale="count",
                domain="minedojo",
            ),
            MeasurementDefinition.scalar(
                "cumulative_reward",
                schema_id="noetrium.measurement.scalar.v1",
                unit="reward",
                semantic_kind="mineclip_conditioned_return",
                scale="continuous",
                domain="minedojo",
            ),
            MeasurementDefinition.scalar(
                "task_success_rate",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="mean_task_success",
                scale="continuous",
                domain="minedojo",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("task-defined-or-environment-bound",),
        limits=TrialBudget(
            "minedojo-neurips2022-mineagent-budget",
            max_steps=4096,
            max_turns=4096,
            max_model_calls=4096,
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=3600.0,
    ).build()


__all__ = [
    "build_minedojo_neurips2022_study",
    "minedojo_neurips2022_trial_protocol",
]
