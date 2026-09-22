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
from research.benchmarks.egoschema import (
    EGOSCHEMA_BENCHMARK_ID,
    EGOSCHEMA_FULL_COUNT,
    EGOSCHEMA_FULL_SPLIT,
    EGOSCHEMA_PUBLIC_COUNT,
    EGOSCHEMA_PUBLIC_SPLIT,
)

from .fidelity import FLASH_VSTREAM_REFERENCE_FIDELITY
from .memory import FLASH_VSTREAM_MEMORY_PROGRAM
from .source import FLASH_VSTREAM_QWEN_ICCV_COMMIT


def flash_vstream_egoschema_trial_protocol(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != EGOSCHEMA_BENCHMARK_ID:
        raise ValueError("Flash-VStream study requires EgoSchema")
    expected = {
        EGOSCHEMA_PUBLIC_SPLIT: EGOSCHEMA_PUBLIC_COUNT,
        EGOSCHEMA_FULL_SPLIT: EGOSCHEMA_FULL_COUNT,
    }.get(split_id)
    if expected is None:
        raise ValueError("unsupported EgoSchema split")
    selected = benchmark.selected_tasks(split_id)
    if len(selected) != expected:
        raise ValueError(
            f"Flash-VStream EgoSchema {split_id} requires {expected} tasks"
        )
    f = FLASH_VSTREAM_REFERENCE_FIDELITY
    return ExperimentTrialProtocolIdentity(
        f"flash-vstream.iccv2025.egoschema.{split_id}.v1",
        canonical_digest(
            {
                "source_commit": FLASH_VSTREAM_QWEN_ICCV_COMMIT,
                "memory_program_digest": FLASH_VSTREAM_MEMORY_PROGRAM.program_digest,
                "benchmark_cut_digest": benchmark.cut_digest,
                "benchmark_split_id": split_id,
                "task_ids": tuple(row.task_id for row in selected),
                "sampling_fps": 1,
                "context_memory": {
                    "configured_length": f.temporal_config_length,
                    "effective_packed_slots": f.temporal_effective_packed_slots,
                    "method": f.temporal_method,
                    "pool_size": f.temporal_pool_size,
                    "pca_dim": f.temporal_pca_dim,
                },
                "augmentation_memory": {
                    "configured_length": f.spatial_config_length,
                    "effective_packed_slots": f.spatial_effective_packed_slots,
                    "method": f.spatial_method,
                    "metric": f.spatial_retrieval_metric,
                },
                "composition_order": f.composition_order,
                "memory_aware_rope": f.memory_aware_rope_enabled,
                "evaluation": (
                    "offline-public-answer"
                    if split_id == EGOSCHEMA_PUBLIC_SPLIT
                    else "official-external-evaluator"
                ),
            }
        ),
    )


def _build_study(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ResearchStudyDefinition:
    protocol = flash_vstream_egoschema_trial_protocol(
        benchmark, split_id=split_id
    )
    return Study(
        project_id="flash-vstream-iccv-2025-reproduction",
        study_id=f"flash-vstream-iccv-2025-egoschema-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="streaming_multimodal_memory_model",
            kind="method",
            implementation="flash-vstream",
            treatment="iccv-2025-qwen-paper-era",
            capabilities=(
                "memory.tensor.read",
                "memory.tensor.write",
                "model.multimodal.generate",
            ),
            configurations=(
                "flash-vstream.csm-60x64",
                "flash-vstream.dam-30x256",
                "flash-vstream.memory-aware-rope",
                "flash-vstream.1fps",
            ),
        ),
        models={
            "multimodal": StudyModel(
                "model.flash-vstream.qwen2-vl-7b-paper-era",
                prompt="flash-vstream.egoschema.multiple-choice",
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
                "context_memory_slot_count",
                schema_id="noetrium.measurement.count.v1",
                unit="slot",
                semantic_kind="compressed_context_memory_slot_count",
                scale="count",
                domain="flash-vstream",
            ),
            MeasurementDefinition.scalar(
                "augmentation_memory_slot_count",
                schema_id="noetrium.measurement.count.v1",
                unit="slot",
                semantic_kind="retrieved_augmentation_memory_slot_count",
                scale="count",
                domain="flash-vstream",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("paper-evaluation-default",),
        limits=TrialBudget(
            f"flash-vstream-iccv2025-egoschema-{split_id}-budget",
            max_steps=512,
            max_turns=64,
            max_model_calls=1,
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=3600.0,
    ).build()


def build_flash_vstream_egoschema_public_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    return _build_study(benchmark, split_id=EGOSCHEMA_PUBLIC_SPLIT)


def build_flash_vstream_egoschema_full_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    return _build_study(benchmark, split_id=EGOSCHEMA_FULL_SPLIT)


__all__ = [
    "build_flash_vstream_egoschema_full_study",
    "build_flash_vstream_egoschema_public_study",
    "flash_vstream_egoschema_trial_protocol",
]
