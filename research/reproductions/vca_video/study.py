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
from research.benchmarks.egoschema import (
    EGOSCHEMA_BENCHMARK_ID,
    EGOSCHEMA_PUBLIC_COUNT,
    EGOSCHEMA_PUBLIC_SPLIT,
)

from .fidelity import VCA_REFERENCE_FIDELITY
from .program import VCA_EXECUTION_SAFETY_ROUNDS, VCA_METHOD_PROGRAM


def vca_egoschema_trial_protocol(
    benchmark: BenchmarkTaskSet,
    *,
    sampling_frame_number: int,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != EGOSCHEMA_BENCHMARK_ID:
        raise ValueError("VCA study requires EgoSchema")
    selected = benchmark.selected_tasks(EGOSCHEMA_PUBLIC_SPLIT)
    if len(selected) != EGOSCHEMA_PUBLIC_COUNT:
        raise ValueError("VCA EgoSchema reproduction requires the 500-task public cut")
    if type(sampling_frame_number) is not int or sampling_frame_number < 1:
        raise ValueError("VCA sampling_frame_number must be positive")
    return ExperimentTrialProtocolIdentity(
        "vca.iccv2025.egoschema-public.paper-authoritative.v1",
        canonical_digest(
            {
                "method_program_digest": VCA_METHOD_PROGRAM.program_digest,
                "benchmark_cut_digest": benchmark.cut_digest,
                "split_id": EGOSCHEMA_PUBLIC_SPLIT,
                "task_ids": tuple(row.task_id for row in selected),
                "sampling_frame_number": sampling_frame_number,
                "memory_frames": VCA_REFERENCE_FIDELITY.egoschema_memory_frames,
                "shared_reward_exploration_model": True,
                "temperature": VCA_REFERENCE_FIDELITY.temperature,
                "tree_search": True,
                "reward_history_conditioning": True,
                "memory_eviction": "lowest_relevance_first",
                "segment_choice": "model_decision_reward_guided_non_greedy",
            }
        ),
    )


def build_vca_egoschema_public_study(
    benchmark: BenchmarkTaskSet,
    *,
    sampling_frame_number: int,
    max_rounds: int = 32,
) -> ResearchStudyDefinition:
    if type(max_rounds) is not int or not 1 <= max_rounds <= VCA_EXECUTION_SAFETY_ROUNDS:
        raise ValueError("VCA max_rounds is outside the reproduction safety ceiling")
    protocol = vca_egoschema_trial_protocol(
        benchmark,
        sampling_frame_number=sampling_frame_number,
    )
    shared_requirement = "model.vca.gpt4o-august-2024"
    return Study(
        project_id="vca-iccv-2025-reproduction",
        study_id="vca-iccv-2025-egoschema-public",
        benchmark=benchmark,
        benchmark_split_id=EGOSCHEMA_PUBLIC_SPLIT,
        method=StudyParticipant(
            role="curiosity_driven_video_agent",
            kind="agent_method",
            implementation="vca-video-curious-agent",
            treatment="iccv-2025-paper-authoritative",
            capabilities=("artifact.video.decode", "model.multimodal.generate"),
            configurations=(
                "vca.segment-tree",
                "vca.self-generated-intrinsic-reward",
                "vca.fixed-relevance-memory-8",
            ),
        ),
        models={
            "vca.shared-vlm.reward": StudyModel(
                shared_requirement,
                prompt="vca.iccv2025.reward-prompt",
            ),
            "vca.shared-vlm.exploration": StudyModel(
                shared_requirement,
                prompt="vca.iccv2025.exploration-prompt",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "multiple_choice_accuracy",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="multiple_choice_accuracy",
                scale="continuous",
                domain="egoschema",
            ),
            MeasurementDefinition.scalar(
                "observed_frame_count",
                schema_id="noetrium.measurement.count.v1",
                unit="frame",
                semantic_kind="observed_frame_count",
                scale="count",
                domain="vca",
            ),
            MeasurementDefinition.scalar(
                "exploration_rounds",
                schema_id="noetrium.measurement.count.v1",
                unit="round",
                semantic_kind="exploration_round_count",
                scale="count",
                domain="vca",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("paper-service-default",),
        limits=TrialBudget(
            "vca-egoschema-paper-authoritative-safety",
            max_steps=VCA_EXECUTION_SAFETY_ROUNDS * 8 + 1,
            max_turns=max_rounds * 2,
            max_model_calls=max_rounds * 2,
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=3600.0,
    ).build()


__all__ = [
    "build_vca_egoschema_public_study",
    "vca_egoschema_trial_protocol",
]
