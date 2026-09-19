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
from research.benchmarks.steve1_paper_prompts import (
    STEVE1_ALL_SPLIT,
    STEVE1_PAPER_PROMPT_NAMES,
    STEVE1_PAPER_PROMPTS_BENCHMARK_ID,
    STEVE1_PAPER_PROMPTS_BLOB_SHA,
    STEVE1_PAPER_PROMPTS_COMMIT,
    STEVE1_RELEASED_CELL_COUNT,
)

from .fidelity import STEVE1_REFERENCE_FIDELITY
from .program import STEVE1_METHOD_PROGRAM


def steve1_neurips2023_prompt_trial_protocol(
    benchmark: BenchmarkTaskSet,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != STEVE1_PAPER_PROMPTS_BENCHMARK_ID:
        raise ValueError(
            "STEVE-1 protocol requires released paper-prompt benchmark"
        )
    selected = benchmark.selected_tasks(STEVE1_ALL_SPLIT)
    if len(selected) != STEVE1_RELEASED_CELL_COUNT:
        raise ValueError("STEVE-1 protocol requires 22 released prompt cells")
    fidelity = STEVE1_REFERENCE_FIDELITY
    return ExperimentTrialProtocolIdentity(
        "steve1.neurips2023.released-paper-prompts.v1",
        canonical_digest({
            "source_commit": STEVE1_PAPER_PROMPTS_COMMIT,
            "paper_prompts_blob_sha": STEVE1_PAPER_PROMPTS_BLOB_SHA,
            "benchmark_cut_digest": benchmark.cut_digest,
            "benchmark_split_id": STEVE1_ALL_SPLIT,
            "task_ids": tuple(row.task_id for row in selected),
            "semantic_prompt_names": STEVE1_PAPER_PROMPT_NAMES,
            "method_program_digest": STEVE1_METHOD_PROGRAM.program_digest,
            "gameplay_length": fidelity.released_runner_gameplay_length,
            "fps": fidelity.runner_fps,
            "text_cond_scale": fidelity.text_cond_scale,
            "visual_cond_scale": fidelity.visual_cond_scale,
            "stochastic_policy_sampling": fidelity.stochastic_policy_sampling,
            "classifier_free_guidance": fidelity.classifier_free_guidance,
            "programmatic_metrics": (
                "log",
                "dirt",
                "seed",
                "travel_dist",
            ),
            "runner_seed": "none-in-released-paper-video-runner",
            "paper_13_task_claim_identity": "not-released",
        }),
    )


def build_steve1_neurips2023_prompt_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    protocol = steve1_neurips2023_prompt_trial_protocol(benchmark)
    fidelity = STEVE1_REFERENCE_FIDELITY
    return Study(
        project_id="steve1-neurips-2023-reproduction",
        study_id="steve1-neurips-2023-released-paper-prompts",
        benchmark=benchmark,
        benchmark_split_id=STEVE1_ALL_SPLIT,
        method=StudyParticipant(
            role="minecraft_vision_language_controller",
            kind="method",
            implementation="steve-1",
            treatment="neurips-2023-released-paper-prompts",
            capabilities=(
                "environment.minecraft.raw-control",
                "model.multimodal.policy",
                "artifact.tensor.read",
                "artifact.tensor.write",
            ),
            configurations=(
                "steve1.mineclip-latent-goal",
                "steve1.classifier-free-guidance",
                "steve1.recurrent-vpt-controller",
                "steve1.text-cond-scale-6",
                "steve1.visual-cond-scale-7",
            ),
        ),
        models={
            "controller": StudyModel(
                "model.steve1.paper-release-vpt",
                prompt="steve1.goal-conditioned-control",
            ),
            "goal_encoder": StudyModel(
                "model.steve1.paper-release-mineclip-prior",
                prompt="steve1.text-or-visual-goal",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "max_log_inventory_count",
                schema_id="noetrium.measurement.count.v1",
                unit="item",
                semantic_kind="steve1_programmatic_inventory_max",
                scale="count",
                domain="log",
            ),
            MeasurementDefinition.scalar(
                "max_dirt_inventory_count",
                schema_id="noetrium.measurement.count.v1",
                unit="item",
                semantic_kind="steve1_programmatic_inventory_max",
                scale="count",
                domain="dirt",
            ),
            MeasurementDefinition.scalar(
                "max_seed_inventory_count",
                schema_id="noetrium.measurement.count.v1",
                unit="item",
                semantic_kind="steve1_programmatic_inventory_max",
                scale="count",
                domain="seed",
            ),
            MeasurementDefinition.scalar(
                "max_travel_distance_blocks",
                schema_id="noetrium.measurement.distance.v1",
                unit="minecraft_block",
                semantic_kind="steve1_programmatic_horizontal_travel",
                scale="continuous",
                domain="minecraft",
            ),
            MeasurementDefinition.scalar(
                "episode_steps",
                schema_id="noetrium.measurement.count.v1",
                unit="environment_step",
                semantic_kind="minecraft_episode_length",
                scale="count",
                domain="steve1",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("released-runner-unseeded",),
        limits=TrialBudget(
            "steve1-neurips2023-released-prompt-budget",
            max_steps=fidelity.released_runner_gameplay_length,
            max_turns=fidelity.released_runner_gameplay_length,
            max_model_calls=fidelity.released_runner_gameplay_length + 1,
            max_working_seconds=1800.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=1800.0,
    ).build()


__all__ = [
    "build_steve1_neurips2023_prompt_study",
    "steve1_neurips2023_prompt_trial_protocol",
]
