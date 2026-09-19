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
from research.benchmarks.ego4d_goalstep import EGO4D_GOALSTEP_BENCHMARK_ID

from .fidelity import PROVIDELLM_REFERENCE_FIDELITY
from .memory import PROVIDELLM_MEMORY_PROGRAM
from .source import PROVIDELLM_PAPER_ERA_COMMIT


def providellm_goalstep_trial_protocol(
    benchmark: BenchmarkTaskSet,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != EGO4D_GOALSTEP_BENCHMARK_ID:
        raise ValueError("ProVideLLM study requires Ego4D Goal-Step")
    selected = benchmark.selected_tasks("val")
    if not selected:
        raise ValueError("ProVideLLM study requires a non-empty GoalStep val cut")
    f = PROVIDELLM_REFERENCE_FIDELITY
    return ExperimentTrialProtocolIdentity(
        "providellm.iccv2025.ego4d-goalstep-val.v1",
        canonical_digest(
            {
                "source_commit": PROVIDELLM_PAPER_ERA_COMMIT,
                "memory_program_digest": PROVIDELLM_MEMORY_PROGRAM.program_digest,
                "benchmark_cut_digest": benchmark.cut_digest,
                "task_ids": tuple(row.task_id for row in selected),
                "short_term_span_seconds": f.runtime_short_term_span_seconds,
                "long_term_span_seconds": f.runtime_long_term_span_seconds,
                "long_term_token_type": f.long_term_token_type,
                "short_term_token_type": f.short_term_token_type,
                "cache_type": f.cache_type,
                "long_term_marker": f.long_term_marker,
                "evaluation": "per-frame-mean-average-precision",
            }
        ),
    )


def build_providellm_goalstep_val_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    protocol = providellm_goalstep_trial_protocol(benchmark)
    return Study(
        project_id="providellm-iccv-2025-reproduction",
        study_id="providellm-iccv-2025-ego4d-goalstep-val",
        benchmark=benchmark,
        benchmark_split_id="val",
        method=StudyParticipant(
            role="streaming_procedural_video_model",
            kind="method",
            implementation="providellm",
            treatment="iccv-2025-paper-era",
            capabilities=(
                "memory.tensor.read",
                "memory.tensor.write",
                "model.multimodal.generate",
            ),
            configurations=(
                "providellm.interleaved-cache",
                "providellm.detr-qformer",
                "providellm.short-term-16s",
                "providellm.long-term-128s",
            ),
        ),
        models={
            "multimodal": StudyModel(
                "model.providellm.1b-5-paper-era",
                prompt="providellm.online-step-detection",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "per_frame_map",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="per_frame_mean_average_precision",
                scale="continuous",
                domain="ego4d-goalstep",
            ),
            MeasurementDefinition.scalar(
                "streaming_fps",
                schema_id="noetrium.measurement.rate.v1",
                unit="frame_per_second",
                semantic_kind="streaming_inference_throughput",
                scale="continuous",
                domain="providellm",
            ),
            MeasurementDefinition.scalar(
                "gpu_memory_gb",
                schema_id="noetrium.measurement.memory.v1",
                unit="gigabyte",
                semantic_kind="gpu_memory_footprint",
                scale="continuous",
                domain="providellm",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("paper-evaluation-default",),
        limits=TrialBudget(
            "providellm-iccv2025-goalstep-val-budget",
            max_steps=32768,
            max_turns=32768,
            max_model_calls=32768,
            max_working_seconds=7200.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=7200.0,
    ).build()


__all__ = [
    "build_providellm_goalstep_val_study",
    "providellm_goalstep_trial_protocol",
]
