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
    EGOSCHEMA_FULL_COUNT,
    EGOSCHEMA_FULL_SPLIT,
    EGOSCHEMA_PUBLIC_COUNT,
    EGOSCHEMA_PUBLIC_SPLIT,
)

from .fidelity import VIDEOAGENT_REFERENCE_FIDELITY
from .memory import VIDEOAGENT_MEMORY_PROGRAM
from .program import VIDEOAGENT_METHOD_PROGRAM
from .source import VIDEOAGENT_AUDITED_COMMIT


def videoagent_egoschema_trial_protocol(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != EGOSCHEMA_BENCHMARK_ID:
        raise ValueError("VideoAgent study requires EgoSchema")
    expected = {
        EGOSCHEMA_PUBLIC_SPLIT: EGOSCHEMA_PUBLIC_COUNT,
        EGOSCHEMA_FULL_SPLIT: EGOSCHEMA_FULL_COUNT,
    }.get(split_id)
    if expected is None:
        raise ValueError("unsupported EgoSchema split")
    selected = benchmark.selected_tasks(split_id)
    if len(selected) != expected:
        raise ValueError(
            f"VideoAgent EgoSchema {split_id} requires {expected} tasks"
        )
    f = VIDEOAGENT_REFERENCE_FIDELITY
    return ExperimentTrialProtocolIdentity(
        f"videoagent.eccv2024.egoschema.{split_id}.v1",
        canonical_digest({
            "source_commit": VIDEOAGENT_AUDITED_COMMIT,
            "method_program_digest": VIDEOAGENT_METHOD_PROGRAM.program_digest,
            "memory_program_digest": VIDEOAGENT_MEMORY_PROGRAM.program_digest,
            "benchmark_cut_digest": benchmark.cut_digest,
            "benchmark_split_id": split_id,
            "task_ids": tuple(row.task_id for row in selected),
            "segment_seconds": f.segment_seconds,
            "tracking_fps": f.tracking_fps,
            "object_embedding_sample_count": (
                f.object_embedding_sample_count
            ),
            "use_reid": f.reidentification_default,
            "segment_localization_top_k": (
                f.segment_localization_top_k
            ),
            "localization_weights": (
                f.segment_visual_score_weight,
                f.segment_textual_score_weight,
            ),
            "main_tools": f.main_tools,
            "object_memory_tools": f.object_memory_tools,
            "reasoner_model": f.main_reasoner_model,
            "object_reasoner_model": f.object_reasoner_model,
            "reasoner_temperature": f.reasoner_temperature,
            "agent_executor_max_iterations": (
                f.agent_executor_max_iterations
            ),
            "agent_executor_early_stopping_method": (
                f.agent_executor_early_stopping_method
            ),
            "vqa_backend": f.default_vqa_backend,
            "vqa_neighbor_radius_segments": (
                f.vqa_neighbor_radius_segments
            ),
            "evaluation": (
                "offline-public-answer"
                if split_id == EGOSCHEMA_PUBLIC_SPLIT
                else "official-external-evaluator"
            ),
        }),
    )


def _build_study(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ResearchStudyDefinition:
    f = VIDEOAGENT_REFERENCE_FIDELITY
    trial = videoagent_egoschema_trial_protocol(
        benchmark,
        split_id=split_id,
    )
    return Study(
        project_id="videoagent-eccv-2024-reproduction",
        study_id=f"videoagent-eccv-2024-egoschema-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="multimodal_memory_agent",
            kind="method",
            implementation="videoagent-memory",
            treatment="eccv-2024-paper-era",
            capabilities=(
                "artifact.video.decode",
                "memory.structured-video.query",
                "model.text.generate",
                "model.video.generate",
                "model.embedding.text",
                "model.embedding.visual",
            ),
            configurations=(
                "videoagent.segment-2s",
                "videoagent.reid-enabled",
                "videoagent.react-15",
                "videoagent.vqa-videollava",
            ),
        ),
        models={
            "reasoner": StudyModel(
                "model.videoagent.gpt4-paper-era",
                prompt="videoagent.main-react.prompt",
            ),
            "object_reasoner": StudyModel(
                "model.videoagent.gpt4-object-memory-paper-era",
                prompt="videoagent.object-memory-react.prompt",
            ),
            "vqa": StudyModel(
                "model.videoagent.videollava-paper-era",
                prompt="videoagent.vqa.prompt",
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
                "agent_tool_iterations",
                schema_id="noetrium.measurement.count.v1",
                unit="iteration",
                semantic_kind="agent_tool_iterations",
                scale="count",
                domain="videoagent",
            ),
            MeasurementDefinition.scalar(
                "memory_query_count",
                schema_id="noetrium.measurement.count.v1",
                unit="query",
                semantic_kind="memory_query_count",
                scale="count",
                domain="videoagent",
            ),
        ),
        trial=trial,
        repetitions=1,
        seeds=("paper-default",),
        limits=TrialBudget(
            f"videoagent-eccv2024-egoschema-{split_id}-budget",
            max_steps=1024,
            max_turns=f.agent_executor_max_iterations,
            max_model_calls=(
                f.agent_executor_max_iterations
                + (
                    f.agent_executor_max_iterations
                    * f.agent_executor_max_iterations
                )
                + f.agent_executor_max_iterations
            ),
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=3600.0,
    ).build()


def build_videoagent_egoschema_public_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    return _build_study(
        benchmark,
        split_id=EGOSCHEMA_PUBLIC_SPLIT,
    )


def build_videoagent_egoschema_full_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    return _build_study(
        benchmark,
        split_id=EGOSCHEMA_FULL_SPLIT,
    )


__all__ = [
    "build_videoagent_egoschema_full_study",
    "build_videoagent_egoschema_public_study",
    "videoagent_egoschema_trial_protocol",
]
