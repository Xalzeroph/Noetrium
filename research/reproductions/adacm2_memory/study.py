from __future__ import annotations
from research.reproductions import _support as _rs



from research.benchmarks.lvu import LVU_BENCHMARK_ID

from .benchmark import ADACM2_LVU_PROTOCOL, ADACM2_LVU_TEST_SPLIT
from .fidelity import (
    ADACM2_REFERENCE_FIDELITY,
    AdaCM2PartitionInterpretation,
)
from .memory import ADACM2_MEMORY_PROGRAM, AdaCM2ReductionSpec


def adacm2_lvu_trial_protocol(
    benchmark,
    *,
    interpretation: AdaCM2PartitionInterpretation,
):
    if benchmark.benchmark_id != LVU_BENCHMARK_ID:
        raise ValueError("AdaCM2 formal protocol requires LVU")
    selected = benchmark.selected_tasks(ADACM2_LVU_TEST_SPLIT)
    if not selected:
        raise ValueError("AdaCM2 LVU test split must be non-empty")
    if not isinstance(
        interpretation,
        AdaCM2PartitionInterpretation,
    ):
        raise TypeError("AdaCM2 study interpretation is invalid")
    spec = AdaCM2ReductionSpec(
        interpretation=interpretation,
        alpha=ADACM2_REFERENCE_FIDELITY.alpha,
        beta=ADACM2_REFERENCE_FIDELITY.beta,
    )
    return _rs.study_protocol(
        f"adacm2.cvpr2025.lvu.{interpretation.value}.v1",
        _rs.canonical_digest({
            "memory_program_digest": ADACM2_MEMORY_PROGRAM.program_digest,
            "publication_revision": (
                ADACM2_REFERENCE_FIDELITY.source_revision
            ),
            "benchmark_cut_digest": benchmark.cut_digest,
            "benchmark_split_id": ADACM2_LVU_TEST_SPLIT,
            "task_ids": tuple(task.task_id for task in selected),
            "full_video_protocol_digest": (
                ADACM2_LVU_PROTOCOL.protocol_digest
            ),
            "fps": ADACM2_REFERENCE_FIDELITY.frame_sampling_fps,
            "alpha": ADACM2_REFERENCE_FIDELITY.alpha,
            "beta": ADACM2_REFERENCE_FIDELITY.beta,
            "partition_interpretation": interpretation.value,
            "reduction_spec_digest": spec.spec_digest,
            "operational_retention_factor": (
                spec.operational_retention_factor
            ),
            "paper_stated_retention_factor": (
                spec.stated_theoretical_retention_factor
            ),
            "paper_internal_inconsistency_preserved": True,
            "visual_encoder": ADACM2_REFERENCE_FIDELITY.visual_encoder,
            "qformer_initialization": (
                ADACM2_REFERENCE_FIDELITY.qformer_initialization
            ),
            "llm": ADACM2_REFERENCE_FIDELITY.llm,
        }),
    )


@_rs.study_factory('benchmark')
def build_adacm2_lvu_study(
    benchmark,
    *,
    interpretation: AdaCM2PartitionInterpretation,
):
    spec = AdaCM2ReductionSpec(
        interpretation=interpretation,
        alpha=ADACM2_REFERENCE_FIDELITY.alpha,
        beta=ADACM2_REFERENCE_FIDELITY.beta,
    )
    protocol = adacm2_lvu_trial_protocol(
        benchmark,
        interpretation=interpretation,
    )
    return _rs.study_spec(project_id="adacm2-cvpr-2025-reproduction",
        study_id=(
            "adacm2-cvpr-2025-lvu-"
            f"{interpretation.value}"
        ),
        benchmark=benchmark,
        benchmark_split_id=ADACM2_LVU_TEST_SPLIT,
        method=_rs.study_participant(
            role="adaptive_cross_modal_memory_model",
            kind="method",
            implementation="adacm2",
            treatment=interpretation.value,
            capabilities=(
                "memory.tensor.read",
                "memory.tensor.write",
                "model.cross-modal-attention",
                "model.multimodal.generate",
            ),
            configurations=(
                "adacm2.full-video-10fps",
                "adacm2.layer-wise-kv-reduction",
                "adacm2.alpha-0.1",
                "adacm2.beta-0.1",
                f"adacm2.partition-{interpretation.value}",
            ),
        ),
        models={
            "multimodal": _rs.study_model(
                "model.adacm2.vicuna7b-v1.1-paper-described",
                prompt="adacm2.lvu.question-template",
            ),
        },
        measurements=(
            _rs.scalar_measurement(
                "task_accuracy",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="classification_accuracy",
                scale="continuous",
                domain="lvu",
            ),
            _rs.scalar_measurement(
                "peak_cache_length",
                schema_id="noetrium.measurement.count.v1",
                unit="visual_token",
                semantic_kind="kv_cache_capacity",
                scale="count",
                domain="adacm2",
            ),
            _rs.scalar_measurement(
                "cache_retention_ratio",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="operational_cache_retention",
                scale="continuous",
                domain="adacm2",
            ),
            _rs.scalar_measurement(
                "paper_stated_retention_factor",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="paper_theoretical_cache_retention",
                scale="continuous",
                domain="adacm2",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("paper-described-evaluation",),
        limits=_rs.trial_budget(
            f"adacm2-cvpr2025-lvu-{interpretation.value}-budget",
            max_steps=16384,
            max_turns=1,
            max_model_calls=16384,
            max_working_seconds=3600.0,
        ),
        replay_level='observational',
        repetition_timeout_seconds=3600.0,
    )


@_rs.study_factory('benchmark')
def build_adacm2_lvu_eq6_literal_study(
    benchmark,
):
    return build_adacm2_lvu_study(
        benchmark,
        interpretation=AdaCM2PartitionInterpretation.EQ6_LITERAL,
    )


@_rs.study_factory('benchmark')
def build_adacm2_lvu_eq8_consistent_study(
    benchmark,
):
    return build_adacm2_lvu_study(
        benchmark,
        interpretation=AdaCM2PartitionInterpretation.EQ8_CONSISTENT,
    )


@_rs.study_factory('benchmark')
def build_adacm2_lvu_ambiguity_studies(
    benchmark,
):
    return (
        build_adacm2_lvu_eq6_literal_study(benchmark),
        build_adacm2_lvu_eq8_consistent_study(benchmark),
    )


__all__ = [
    "adacm2_lvu_trial_protocol",
    "build_adacm2_lvu_ambiguity_studies",
    "build_adacm2_lvu_eq6_literal_study",
    "build_adacm2_lvu_eq8_consistent_study",
]
