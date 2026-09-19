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

from .fidelity import VIDEOLLAMB_REFERENCE_FIDELITY
from .memory import VIDEOLLAMB_MEMORY_PROGRAM
from .source import VIDEOLLAMB_PAPER_ERA_COMMIT


VIDEOLLAMB_EGOSCHEMA_CHECKPOINT = "llava-7b-ft-rmt1x-lvcn_16_4_poo12_new_loss"
VIDEOLLAMB_EGOSCHEMA_NUM_FRAMES = 16


def videollamb_egoschema_trial_protocol(
    benchmark: BenchmarkTaskSet,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != EGOSCHEMA_BENCHMARK_ID:
        raise ValueError("VideoLLaMB study requires EgoSchema")
    selected = benchmark.selected_tasks(EGOSCHEMA_PUBLIC_SPLIT)
    if len(selected) != EGOSCHEMA_PUBLIC_COUNT:
        raise ValueError("VideoLLaMB requires the 500-task EgoSchema public cut")
    fidelity = VIDEOLLAMB_REFERENCE_FIDELITY
    return ExperimentTrialProtocolIdentity(
        "videollamb.iccv2025.egoschema-public.paper-era.v1",
        canonical_digest({
            "source_commit": VIDEOLLAMB_PAPER_ERA_COMMIT,
            "memory_program_digest": VIDEOLLAMB_MEMORY_PROGRAM.program_digest,
            "benchmark_cut_digest": benchmark.cut_digest,
            "benchmark_split_id": EGOSCHEMA_PUBLIC_SPLIT,
            "task_ids": tuple(row.task_id for row in selected),
            "checkpoint": VIDEOLLAMB_EGOSCHEMA_CHECKPOINT,
            "num_frames": VIDEOLLAMB_EGOSCHEMA_NUM_FRAMES,
            "memory_token_count": 32,
            "bridge_layer_count": fidelity.bridge_transformer_layers,
            "retrieval_layer_count": 1,
            "scene_tiling": fidelity.scene_tiling,
            "training_frames": fidelity.training_frames,
            "training_segments": fidelity.training_segments,
            "evaluation": "official-egoschema-subset-accuracy",
        }),
    )


def build_videollamb_egoschema_public_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    fidelity = VIDEOLLAMB_REFERENCE_FIDELITY
    protocol = videollamb_egoschema_trial_protocol(benchmark)
    return Study(
        project_id="videollamb-iccv-2025-reproduction",
        study_id="videollamb-iccv-2025-egoschema-public",
        benchmark=benchmark,
        benchmark_split_id=EGOSCHEMA_PUBLIC_SPLIT,
        method=StudyParticipant(
            role="recurrent_multimodal_memory_model",
            kind="method",
            implementation="videollamb",
            treatment="iccv-2025-paper-era",
            capabilities=(
                "memory.tensor.read",
                "memory.tensor.write",
                "model.multimodal.generate",
            ),
            configurations=(
                "videollamb.rmt-r-transformer1x",
                "videollamb.memory-tokens-32",
                "videollamb.scene-tiling",
                "videollamb.num-frames-16",
            ),
        ),
        models={
            "multimodal": StudyModel(
                "model.videollamb.llava15-7b-rmt1x",
                prompt="videollamb.egoschema.zero-shot-mcq",
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
                "processed_segment_count",
                schema_id="noetrium.measurement.count.v1",
                unit="segment",
                semantic_kind="semantic_video_segment_count",
                scale="count",
                domain="videollamb",
            ),
            MeasurementDefinition.scalar(
                "memory_cache_size",
                schema_id="noetrium.measurement.count.v1",
                unit="memory_state",
                semantic_kind="recurrent_memory_cache_size",
                scale="count",
                domain="videollamb",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("paper-evaluation-default",),
        limits=TrialBudget(
            "videollamb-iccv2025-egoschema-public-budget",
            max_steps=512,
            max_turns=64,
            max_model_calls=1,
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=3600.0,
    ).build()


__all__ = [
    "VIDEOLLAMB_EGOSCHEMA_CHECKPOINT",
    "VIDEOLLAMB_EGOSCHEMA_NUM_FRAMES",
    "build_videollamb_egoschema_public_study",
    "videollamb_egoschema_trial_protocol",
]
