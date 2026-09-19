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
from research.benchmarks.moviechat_1k import (
    MOVIECHAT_1K_BENCHMARK_ID,
    MOVIECHAT_1K_BREAKPOINT_QA_PER_VIDEO,
    MOVIECHAT_1K_GLOBAL_QA_PER_VIDEO,
    MOVIECHAT_1K_TEST_SPLIT,
    MOVIECHAT_1K_VIDEO_COUNT,
)

from .fidelity import MOVIECHAT_REFERENCE_FIDELITY
from .memory import MOVIECHAT_MEMORY_PROGRAM
from .source import MOVIECHAT_AUDITED_COMMIT


def moviechat_cvpr2024_trial_protocol(
    benchmark: BenchmarkTaskSet,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != MOVIECHAT_1K_BENCHMARK_ID:
        raise ValueError(
            "MovieChat CVPR 2024 protocol requires MovieChat-1K"
        )
    selected = benchmark.selected_tasks(MOVIECHAT_1K_TEST_SPLIT)
    if len(selected) != MOVIECHAT_1K_VIDEO_COUNT:
        raise ValueError(
            "MovieChat CVPR 2024 protocol requires 1000-video test cut"
        )

    fidelity = MOVIECHAT_REFERENCE_FIDELITY
    return ExperimentTrialProtocolIdentity(
        "moviechat.cvpr2024.moviechat-1k.v1",
        canonical_digest({
            "memory_program_digest": MOVIECHAT_MEMORY_PROGRAM.program_digest,
            "source_commit": MOVIECHAT_AUDITED_COMMIT,
            "benchmark_cut_digest": benchmark.cut_digest,
            "benchmark_split_id": MOVIECHAT_1K_TEST_SPLIT,
            "video_task_ids": tuple(row.task_id for row in selected),
            "video_count": MOVIECHAT_1K_VIDEO_COUNT,
            "global_questions_per_video": (
                MOVIECHAT_1K_GLOBAL_QA_PER_VIDEO
            ),
            "breakpoint_questions_per_video": (
                MOVIECHAT_1K_BREAKPOINT_QA_PER_VIDEO
            ),
            "global_execution_semantics": (
                "reset-once-build-entire-video-answer-three"
            ),
            "breakpoint_execution_semantics": (
                "reset-before-each-question-build-prefix-to-frame"
            ),
            "fragments_per_video": fidelity.fragments_per_video,
            "frames_per_fragment": fidelity.frames_per_fragment,
            "short_memory_length": fidelity.short_memory_length,
            "short_memory_merge": fidelity.short_memory_merge,
            "long_memory_length": fidelity.long_memory_length,
            "position_capacity": fidelity.position_capacity,
            "seed": fidelity.evaluation_seed,
            "num_beams": fidelity.generation_num_beams,
            "temperature": fidelity.generation_temperature,
            "max_new_tokens": fidelity.generation_max_new_tokens,
            "max_context_length": fidelity.generation_max_context_length,
            "qa_evaluator_model": fidelity.qa_evaluator_model,
            "qa_evaluator_consistency_threshold": (
                fidelity.qa_evaluator_consistency_threshold
            ),
            "qa_evaluator_source": (
                "eval_code/Acc_score/run_eval_qa_moviechat.py"
            ),
            "qa_evaluator_outputs": ("yes_no_accuracy", "score_0_to_5"),
        }),
    )


def build_moviechat_cvpr2024_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    fidelity = MOVIECHAT_REFERENCE_FIDELITY
    protocol = moviechat_cvpr2024_trial_protocol(benchmark)

    return Study(
        project_id="moviechat-cvpr-2024-reproduction",
        study_id="moviechat-cvpr-2024-moviechat-1k",
        benchmark=benchmark,
        benchmark_split_id=MOVIECHAT_1K_TEST_SPLIT,
        method=StudyParticipant(
            role="multimodal_memory_model",
            kind="method",
            implementation="moviechat",
            treatment="cvpr-2024-paper-era",
            capabilities=(
                "memory.tensor.read",
                "memory.tensor.write",
                "model.multimodal.generate",
                "evaluation.semantic-qa-judge",
            ),
            configurations=(
                "moviechat.vicuna7b",
                "moviechat.short-memory-18",
                "moviechat.long-memory-256",
                "moviechat.fragments-128x8",
            ),
        ),
        models={
            "multimodal": StudyModel(
                "model.moviechat.vicuna7b",
                prompt="moviechat.long-video-qa.prompt",
            ),
            "judge": StudyModel(
                "model.moviechat.paper-era-qa-judge",
                prompt="moviechat.qa-evaluation.prompt",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "global_accuracy",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="semantic_qa_accuracy",
                scale="continuous",
                domain="moviechat_global",
            ),
            MeasurementDefinition.scalar(
                "breakpoint_accuracy",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="semantic_qa_accuracy",
                scale="continuous",
                domain="moviechat_breakpoint",
            ),
            MeasurementDefinition.scalar(
                "global_semantic_score",
                schema_id="noetrium.measurement.score.v1",
                unit="score_0_to_5",
                semantic_kind="semantic_qa_match_score",
                scale="continuous",
                domain="moviechat_global",
            ),
            MeasurementDefinition.scalar(
                "breakpoint_semantic_score",
                schema_id="noetrium.measurement.score.v1",
                unit="score_0_to_5",
                semantic_kind="semantic_qa_match_score",
                scale="continuous",
                domain="moviechat_breakpoint",
            ),
            MeasurementDefinition.scalar(
                "peak_long_memory_length",
                schema_id="noetrium.measurement.count.v1",
                unit="frame_embedding",
                semantic_kind="memory_capacity",
                scale="count",
                domain="moviechat",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=(str(fidelity.evaluation_seed),),
        limits=TrialBudget(
            "moviechat-cvpr2024-moviechat-1k-budget",
            max_steps=1024,
            max_turns=(
                MOVIECHAT_1K_GLOBAL_QA_PER_VIDEO
                + MOVIECHAT_1K_BREAKPOINT_QA_PER_VIDEO
            ),
            max_model_calls=(
                2
                * (
                    MOVIECHAT_1K_GLOBAL_QA_PER_VIDEO
                    + MOVIECHAT_1K_BREAKPOINT_QA_PER_VIDEO
                )
            ),
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=3600.0,
    ).build()


__all__ = [
    "build_moviechat_cvpr2024_study",
    "moviechat_cvpr2024_trial_protocol",
]
