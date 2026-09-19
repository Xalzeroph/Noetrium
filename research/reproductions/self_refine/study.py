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
from research.benchmarks.commongen import COMMONGEN_BENCHMARK_ID

from .fidelity import SELF_REFINE_FIDELITY
from .program import SELF_REFINE_COMMONGEN_METHOD_PROGRAM


def self_refine_commongen_trial_protocol(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != COMMONGEN_BENCHMARK_ID:
        raise ValueError("Self-Refine CommonGen study requires CommonGen benchmark")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("Self-Refine CommonGen study requires a non-empty split")
    return ExperimentTrialProtocolIdentity(
        "self-refine.commongen.paper-era.v1",
        canonical_digest(
            {
                "program_digest": SELF_REFINE_COMMONGEN_METHOD_PROGRAM.program_digest,
                "benchmark_cut_digest": benchmark.cut_digest,
                "split_id": split_id,
                "task_ids": tuple(row.task_id for row in selected),
                "source_commit": SELF_REFINE_FIDELITY.audited_commit,
                "prompt_blobs": (
                    SELF_REFINE_FIDELITY.commongen_init_prompt_blob,
                    SELF_REFINE_FIDELITY.commongen_feedback_prompt_blob,
                    SELF_REFINE_FIDELITY.commongen_iterate_prompt_blob,
                ),
                "max_attempts": SELF_REFINE_FIDELITY.commongen_max_attempts,
                "temperature": SELF_REFINE_FIDELITY.commongen_temperature,
                "max_output_tokens": SELF_REFINE_FIDELITY.commongen_max_output_tokens,
                "stop_condition": SELF_REFINE_FIDELITY.commongen_stop_condition,
                "shared_model_across_init_feedback_iterate": True,
            }
        ),
    )


def build_self_refine_commongen_study(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ResearchStudyDefinition:
    protocol = self_refine_commongen_trial_protocol(
        benchmark,
        split_id=split_id,
    )
    measurements = (
        MeasurementDefinition.scalar(
            "direct_concept_success",
            schema_id="noetrium.measurement.binary-scalar.v1",
            unit="ratio",
            semantic_kind="concept_coverage_success",
            scale="binary",
            domain="commongen",
        ),
        MeasurementDefinition.scalar(
            "direct_commonsense_success",
            schema_id="noetrium.measurement.binary-scalar.v1",
            unit="ratio",
            semantic_kind="commonsense_feedback_success",
            scale="binary",
            domain="commongen",
        ),
        MeasurementDefinition.scalar(
            "direct_success",
            schema_id="noetrium.measurement.binary-scalar.v1",
            unit="ratio",
            semantic_kind="direct_generation_success",
            scale="binary",
            domain="commongen",
        ),
        MeasurementDefinition.scalar(
            "iter_concept_success",
            schema_id="noetrium.measurement.binary-scalar.v1",
            unit="ratio",
            semantic_kind="concept_coverage_success_after_refinement",
            scale="binary",
            domain="commongen",
        ),
        MeasurementDefinition.scalar(
            "iter_commonsense_success",
            schema_id="noetrium.measurement.binary-scalar.v1",
            unit="ratio",
            semantic_kind="commonsense_feedback_success_after_refinement",
            scale="binary",
            domain="commongen",
        ),
        MeasurementDefinition.scalar(
            "iter_success",
            schema_id="noetrium.measurement.binary-scalar.v1",
            unit="ratio",
            semantic_kind="iterative_refinement_success",
            scale="binary",
            domain="commongen",
        ),
        MeasurementDefinition.scalar(
            "attempt_count",
            schema_id="noetrium.measurement.count.v1",
            unit="attempt",
            semantic_kind="refinement_attempt_count",
            scale="count",
            domain="self_refine",
        ),
    )
    return Study(
        project_id="self-refine-neurips-2023-reproduction",
        study_id=f"self-refine-commongen-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="self_refine",
            kind="agent_method",
            implementation="self-refine",
            treatment="paper-era-commongen",
            capabilities=(),
            configurations=(
                "self-refine.commongen.paper-era",
                "self-refine.commongen.prompt-bundle",
            ),
        ),
        models={
            # One role and one binding intentionally serve init, feedback and
            # iterate, preserving the paper's same-model reuse constraint.
            "self-refine.model": StudyModel(
                "model.self-refine.shared",
                prompt="self-refine.commongen.paper-era-prompts",
            ),
        },
        measurements=measurements,
        trial=protocol,
        repetitions=1,
        seeds=("0",),
        limits=TrialBudget(
            "self-refine-commongen-4-attempts",
            max_steps=64,
            max_turns=SELF_REFINE_FIDELITY.commongen_max_attempts * 2,
            max_model_calls=SELF_REFINE_FIDELITY.commongen_max_attempts * 2,
            max_working_seconds=1800.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "build_self_refine_commongen_study",
    "self_refine_commongen_trial_protocol",
]
