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
from research.benchmarks.vima_bench import (
    VIMA_BENCHMARK_ID,
    VIMA_CAMERA_READY_EXECUTABLE_SEED,
    VIMA_PARTITION_TASKS,
)

from .fidelity import VIMA_REFERENCE_FIDELITY
from .program import VIMA_METHOD_PROGRAM
from .source import VIMA_BENCH_AUDITED_COMMIT, VIMA_POLICY_AUDITED_COMMIT


def vima_icml2023_trial_protocol(
    benchmark: BenchmarkTaskSet,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != VIMA_BENCHMARK_ID:
        raise ValueError("VIMA protocol requires VIMA-Bench")
    if len(benchmark.selected_tasks("all")) != 43:
        raise ValueError("VIMA protocol requires 43 task-partition cells")
    return ExperimentTrialProtocolIdentity(
        "vima.icml2023.camera-ready.v1",
        canonical_digest({
            "policy_source_commit": VIMA_POLICY_AUDITED_COMMIT,
            "benchmark_source_commit": VIMA_BENCH_AUDITED_COMMIT,
            "benchmark_cut_digest": benchmark.cut_digest,
            "method_program_digest": VIMA_METHOD_PROGRAM.program_digest,
            "partition_tasks": VIMA_PARTITION_TASKS,
            "camera_ready_executable_seed": (
                VIMA_CAMERA_READY_EXECUTABLE_SEED
            ),
            "paper_success_semantics": "binary-no-partial-reward",
            "paper_final_metric": "mean-success-rate-over-evaluated-tasks",
            "episode_bonus_steps": (
                VIMA_REFERENCE_FIDELITY.episode_bonus_steps
            ),
            "prompt_semantics": "interleaved-text-object-tokens",
            "observation_semantics": "object-centric-front-top-ee",
            "action_semantics": "two-pose-six-component-discretized",
        }),
    )


def build_vima_icml2023_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    protocol = vima_icml2023_trial_protocol(benchmark)
    return Study(
        project_id="vima-icml-2023-reproduction",
        study_id="vima-icml-2023-vima-bench-camera-ready",
        benchmark=benchmark,
        benchmark_split_id="all",
        method=StudyParticipant(
            role="multimodal_embodied_policy",
            kind="method",
            implementation="vima",
            treatment="icml-2023-camera-ready",
            capabilities=(
                "environment.embodied",
                "model.multimodal.policy",
                "artifact.tensor.read",
                "artifact.tensor.write",
            ),
            configurations=(
                "vima.object-centric",
                "vima.cross-attention",
                "vima.autoregressive-history",
                "vima.position-bins-50x100",
                "vima.rotation-bins-50x50x50x50",
            ),
        ),
        models={
            "policy": StudyModel(
                "model.vima.camera-ready-policy",
                prompt="vima.multimodal-prompt",
            ),
            "prompt_encoder": StudyModel(
                "model.vima.t5-base-frozen",
                prompt="vima.prompt-encoder",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "episode_success",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="binary_task_success",
                scale="binary",
                domain="vima_bench",
            ),
            MeasurementDefinition.scalar(
                "episode_steps",
                schema_id="noetrium.measurement.count.v1",
                unit="environment_step",
                semantic_kind="embodied_episode_length",
                scale="count",
                domain="vima_bench",
            ),
            MeasurementDefinition.scalar(
                "partition_success_rate",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="mean_binary_success_by_generalization_level",
                scale="continuous",
                domain="vima_bench",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=(str(VIMA_CAMERA_READY_EXECUTABLE_SEED),),
        limits=TrialBudget(
            "vima-icml2023-camera-ready-budget",
            max_steps=512,
            max_turns=512,
            max_model_calls=512,
            max_working_seconds=1800.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=1800.0,
    ).build()


__all__ = [
    "build_vima_icml2023_study",
    "vima_icml2023_trial_protocol",
]
