from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentTrialProtocolIdentity,
)
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkAssignmentMode,
    BenchmarkTaskSet,
    MeasurementDefinition,
    ReplayLevel,
    ResearchStudyDefinition,
    Study,
    StudyModel,
    StudyParticipant,
    TrialBudget,
)
from research.benchmarks.mgsm import (
    MGSM_ADAS_TEST_SPLIT,
    MGSM_ADAS_VALID_SIZE,
    MGSM_ADAS_VALID_SPLIT,
    MGSM_BENCHMARK_ID,
)

from .fidelity import ADAS_META_AGENT_SEARCH_FIDELITY
from .program import ADAS_MGSM_METHOD_PROGRAM

_CANDIDATE_EXECUTION_CAPABILITY = "workbench.candidate-program.execute"


def adas_mgsm_search_trial_protocol(
    benchmark: BenchmarkTaskSet,
) -> ExperimentTrialProtocolIdentity:
    fidelity = ADAS_META_AGENT_SEARCH_FIDELITY
    if benchmark.benchmark_id != MGSM_BENCHMARK_ID:
        raise ValueError("ADAS formal search protocol requires MGSM")
    validation = benchmark.selected_tasks(MGSM_ADAS_VALID_SPLIT)
    if len(validation) != fidelity.validation_size:
        raise ValueError(
            "ADAS MGSM validation split cardinality drifted: "
            f"expected={fidelity.validation_size} actual={len(validation)}"
        )
    # The test split is frozen into the benchmark identity but is deliberately
    # excluded from search fitness and candidate selection.
    test = benchmark.selected_tasks(MGSM_ADAS_TEST_SPLIT)
    if len(test) != fidelity.test_size:
        raise ValueError(
            "ADAS MGSM test split cardinality drifted: "
            f"expected={fidelity.test_size} actual={len(test)}"
        )
    return ExperimentTrialProtocolIdentity(
        "adas.meta-agent-search.mgsm.validation.v1",
        canonical_digest(
            {
                "program_digest": ADAS_MGSM_METHOD_PROGRAM.program_digest,
                "source_commit": fidelity.audited_commit,
                "source_artifact": fidelity.source_artifact,
                "prompt_artifact": fidelity.prompt_artifact,
                "benchmark_cut_digest": benchmark.cut_digest,
                "validation_split_id": MGSM_ADAS_VALID_SPLIT,
                "validation_task_ids": tuple(row.task_id for row in validation),
                "test_split_id": MGSM_ADAS_TEST_SPLIT,
                "test_task_ids": tuple(row.task_id for row in test),
                "benchmark_assignment_mode": BenchmarkAssignmentMode.CUT.value,
                "generation_budget": fidelity.generation_budget,
                "reflection_passes": fidelity.reflection_passes_per_generation,
                "candidate_execution_attempt_budget": (
                    fidelity.candidate_execution_attempt_budget
                ),
                "low_accuracy_debug_threshold": (
                    fidelity.low_accuracy_debug_threshold
                ),
                "bootstrap_samples": fidelity.bootstrap_samples,
                "bootstrap_confidence_level": (
                    fidelity.bootstrap_confidence_level
                ),
                "test_data_visible_to_search": False,
            }
        ),
    )


def build_adas_mgsm_search_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    fidelity = ADAS_META_AGENT_SEARCH_FIDELITY
    protocol = adas_mgsm_search_trial_protocol(benchmark)

    return Study(
        project_id="adas-iclr-2025-reproduction",
        study_id="adas-iclr-2025-mgsm-meta-agent-search",
        benchmark=benchmark,
        benchmark_split_id=MGSM_ADAS_VALID_SPLIT,
        benchmark_assignment_mode=BenchmarkAssignmentMode.CUT,
        method=StudyParticipant(
            role="meta_search",
            kind="method",
            implementation="adas-meta-agent-search",
            treatment="paper-era-mgsm-meta-agent-search",
            capabilities=(_CANDIDATE_EXECUTION_CAPABILITY,),
            configurations=(
                "adas.meta-agent-search.mgsm",
                "adas.candidate-execution.mgsm-validation",
            ),
        ),
        models={
            "meta_agent": StudyModel(
                "model.adas.meta-agent",
                prompt="adas.meta-agent.mgsm.prompt",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "best_validation_accuracy",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="best_search_validation_accuracy",
                scale="continuous",
                domain="mgsm",
            ),
            MeasurementDefinition.scalar(
                "best_fitness_median",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="best_bootstrap_fitness_median",
                scale="continuous",
                domain="mgsm",
            ),
            MeasurementDefinition.scalar(
                "archive_size",
                schema_id="noetrium.measurement.count.v1",
                unit="candidate",
                semantic_kind="agent_design_archive_size",
                scale="count",
                domain="meta_search",
            ),
            MeasurementDefinition.scalar(
                "successful_generation_count",
                schema_id="noetrium.measurement.count.v1",
                unit="generation",
                semantic_kind="accepted_agent_design_generation",
                scale="count",
                domain="meta_search",
            ),
            MeasurementDefinition.scalar(
                "failed_generation_count",
                schema_id="noetrium.measurement.count.v1",
                unit="generation",
                semantic_kind="skipped_agent_design_generation",
                scale="count",
                domain="meta_search",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=(str(fidelity.shuffle_seed),),
        limits=TrialBudget(
            "adas-iclr-2025-mgsm-meta-search",
            max_steps=4096,
            max_turns=(
                fidelity.generation_budget
                * (
                    1
                    + fidelity.reflection_passes_per_generation
                    + fidelity.candidate_execution_attempt_budget
                )
            ),
            max_model_calls=(
                fidelity.generation_budget
                * (
                    1
                    + fidelity.reflection_passes_per_generation
                    + fidelity.candidate_execution_attempt_budget
                )
            ),
            max_working_seconds=86400.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=86400.0,
    ).build()


__all__ = [
    "adas_mgsm_search_trial_protocol",
    "build_adas_mgsm_search_study",
]
