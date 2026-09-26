from __future__ import annotations
from research.reproductions import _support as _rs
from research.benchmarks.egoschema import (
    EGOSCHEMA_BENCHMARK_ID,
    EGOSCHEMA_PUBLIC_COUNT,
    EGOSCHEMA_PUBLIC_SPLIT,
)

from .fidelity import DRVIDEO_REFERENCE_FIDELITY
from .program import DRVIDEO_METHOD_PROGRAM
from .source import DRVIDEO_OFFICIAL_COMMIT


DRVIDEO_EGOSCHEMA_AGENT_MODEL = "gpt-4-1106-preview"
DRVIDEO_EGOSCHEMA_CAPTIONER = "lavila"
DRVIDEO_EGOSCHEMA_SAMPLING_FPS = 0.5


def drvideo_egoschema_trial_protocol(
    benchmark,
):
    if benchmark.benchmark_id != EGOSCHEMA_BENCHMARK_ID:
        raise ValueError("DrVideo study requires EgoSchema")
    selected = benchmark.selected_tasks(EGOSCHEMA_PUBLIC_SPLIT)
    if len(selected) != EGOSCHEMA_PUBLIC_COUNT:
        raise ValueError("DrVideo requires the 500-task EgoSchema public cut")

    fidelity = DRVIDEO_REFERENCE_FIDELITY
    return _rs.study_protocol(
        "drvideo.cvpr2025.egoschema-public.paper-authoritative.v1",
        _rs.canonical_digest(
            {
                "source_commit": DRVIDEO_OFFICIAL_COMMIT,
                "method_program_digest": DRVIDEO_METHOD_PROGRAM.program_digest,
                "benchmark_cut_digest": benchmark.cut_digest,
                "benchmark_split_id": EGOSCHEMA_PUBLIC_SPLIT,
                "task_ids": tuple(row.task_id for row in selected),
                "sampling_fps": DRVIDEO_EGOSCHEMA_SAMPLING_FPS,
                "initial_top_k": fidelity.paper_initial_top_k,
                "max_agent_rounds": fidelity.max_agent_rounds,
                "maximum_added_frames_per_round": (
                    fidelity.maximum_added_frames_per_round
                ),
                "augmentation_types": fidelity.augmentation_types,
                "captioner": DRVIDEO_EGOSCHEMA_CAPTIONER,
                "agent_model": DRVIDEO_EGOSCHEMA_AGENT_MODEL,
                "retrieval_metric": "cosine_similarity",
                "final_answering": "chain_of_thought",
            }
        ),
    )


@_rs.study_factory('benchmark')
def build_drvideo_egoschema_public_study(
    benchmark,
):
    fidelity = DRVIDEO_REFERENCE_FIDELITY
    protocol = drvideo_egoschema_trial_protocol(benchmark)
    return _rs.study_spec(project_id="drvideo-cvpr-2025-reproduction",
        study_id="drvideo-cvpr-2025-egoschema-public",
        benchmark=benchmark,
        benchmark_split_id=EGOSCHEMA_PUBLIC_SPLIT,
        method=_rs.study_participant(
            role="document_retrieval_video_agent",
            kind="agent_method",
            implementation="drvideo",
            treatment="cvpr-2025-paper-authoritative",
            capabilities=(
                "data.semantic-similarity",
                "model.multimodal.generate",
            ),
            configurations=(
                "drvideo.document-retrieval-top5",
                "drvideo.agent-loop-2-rounds",
                "drvideo.caption-vqa-augmentation",
                "drvideo.cot-answering",
                "drvideo.egoschema-0.5fps",
            ),
        ),
        models={
            "captioner": _rs.study_model(
                "model.lavila.egoschema-captioner",
                prompt="drvideo.egoschema.coarse-document",
            ),
            "agent": _rs.study_model(
                "model.openai.gpt-4-1106-preview",
                prompt="drvideo.cvpr2025.agent-prompts",
            ),
        },
        measurements=(
            _rs.scalar_measurement(
                "multiple_choice_accuracy",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="multiple_choice_accuracy",
                scale="continuous",
                domain="egoschema",
            ),
            _rs.scalar_measurement(
                "retrieved_frame_count",
                schema_id="noetrium.measurement.count.v1",
                unit="frame",
                semantic_kind="retrieved_video_frame_count",
                scale="count",
                domain="drvideo",
            ),
            _rs.scalar_measurement(
                "augmented_frame_count",
                schema_id="noetrium.measurement.count.v1",
                unit="frame",
                semantic_kind="augmented_video_frame_count",
                scale="count",
                domain="drvideo",
            ),
            _rs.scalar_measurement(
                "interaction_rounds",
                schema_id="noetrium.measurement.count.v1",
                unit="round",
                semantic_kind="adaptive_document_interaction_round_count",
                scale="count",
                domain="drvideo",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("paper-service-default",),
        limits=_rs.trial_budget(
            "drvideo-cvpr2025-egoschema-public-safety",
            max_steps=96,
            max_turns=16,
            max_model_calls=8,
            max_working_seconds=3600.0,
        ),
        replay_level='observational',
        repetition_timeout_seconds=3600.0,
    )


__all__ = [
    "DRVIDEO_EGOSCHEMA_AGENT_MODEL",
    "DRVIDEO_EGOSCHEMA_CAPTIONER",
    "DRVIDEO_EGOSCHEMA_SAMPLING_FPS",
    "build_drvideo_egoschema_public_study",
    "drvideo_egoschema_trial_protocol",
]
