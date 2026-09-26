from __future__ import annotations
from research.reproductions import _support as _rs
from research.benchmarks.lvu import LVU_BENCHMARK_ID, MA_LMM_LVU_PROTOCOL

from .benchmark import MA_LMM_LVU_TEST_SPLIT
from .fidelity import MALMM_REFERENCE_FIDELITY
from .memory import MA_LMM_MEMORY_PROGRAM
from .source import MALMM_AUDITED_COMMIT


def ma_lmm_lvu_trial_protocol(
    benchmark,
):
    if benchmark.benchmark_id != LVU_BENCHMARK_ID:
        raise ValueError("MA-LMM formal LVU protocol requires LVU benchmark")
    selected = benchmark.selected_tasks(MA_LMM_LVU_TEST_SPLIT)
    if not selected:
        raise ValueError("MA-LMM LVU test split must be non-empty")

    expected_families = {
        f"lvu_{task}" for task in MA_LMM_LVU_PROTOCOL.task_ids
    }
    present_families = {task.family for task in selected}
    if not expected_families.issubset(present_families):
        raise ValueError("MA-LMM LVU test split does not cover all seven tasks")

    return _rs.study_protocol(
        "ma-lmm.cvpr2024.lvu.v1",
        _rs.canonical_digest({
            "memory_program_digest": MA_LMM_MEMORY_PROGRAM.program_digest,
            "source_commit": MALMM_AUDITED_COMMIT,
            "benchmark_cut_digest": benchmark.cut_digest,
            "benchmark_split_id": MA_LMM_LVU_TEST_SPLIT,
            "selection_protocol_digest": MA_LMM_LVU_PROTOCOL.protocol_digest,
            "task_ids": tuple(task.task_id for task in selected),
            "memory_bank_length": (
                MALMM_REFERENCE_FIDELITY.long_video_memory_bank_length
            ),
            "num_query_tokens": MALMM_REFERENCE_FIDELITY.query_token_count,
            "history_seconds": MA_LMM_LVU_PROTOCOL.history_seconds,
            "stride_seconds": MA_LMM_LVU_PROTOCOL.stride_seconds,
            "sampled_frames": MA_LMM_LVU_PROTOCOL.sampled_frames,
            "fps": MA_LMM_LVU_PROTOCOL.fps,
            "num_beams": 5,
            "seed": 42,
            "paper_model_family": "instructblip-vicuna-7b",
        }),
    )


@_rs.study_factory('benchmark')
def build_ma_lmm_lvu_study(
    benchmark,
):
    protocol = ma_lmm_lvu_trial_protocol(benchmark)
    return _rs.study_spec(project_id="ma-lmm-cvpr-2024-reproduction",
        study_id="ma-lmm-cvpr-2024-lvu",
        benchmark=benchmark,
        benchmark_split_id=MA_LMM_LVU_TEST_SPLIT,
        method=_rs.study_participant(
            role="multimodal_memory_model",
            kind="method",
            implementation="ma-lmm",
            treatment="cvpr-2024-paper-era",
            capabilities=(
                "memory.tensor.read",
                "memory.tensor.write",
                "model.multimodal.generate",
            ),
            configurations=(
                "ma-lmm.instructblip-vicuna7b",
                "ma-lmm.lvu.memory-bank-20",
                "ma-lmm.lvu.100-frame-window",
            ),
        ),
        models={
            "multimodal": _rs.study_model(
                "model.ma-lmm.instructblip-vicuna7b",
                prompt="ma-lmm.lvu.question-template",
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
                "peak_memory_bank_length",
                schema_id="noetrium.measurement.count.v1",
                unit="temporal_slot",
                semantic_kind="memory_capacity",
                scale="count",
                domain="ma-lmm",
            ),
            _rs.scalar_measurement(
                "memory_compression_count",
                schema_id="noetrium.measurement.count.v1",
                unit="compression",
                semantic_kind="memory_compression",
                scale="count",
                domain="ma-lmm",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("42",),
        limits=_rs.trial_budget(
            "ma-lmm-cvpr2024-lvu-budget",
            max_steps=512,
            max_turns=1,
            max_model_calls=1,
            max_working_seconds=1800.0,
        ),
        replay_level='observational',
        repetition_timeout_seconds=1800.0,
    )


__all__ = [
    "build_ma_lmm_lvu_study",
    "ma_lmm_lvu_trial_protocol",
]
