from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.experiment.api import ExperimentTrialProtocolIdentity
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
from research.benchmarks.visualwebarena import (
    VISUALWEBARENA_BENCHMARK_ID,
    visualwebarena_site_split_id,
)

from .fidelity import EXACT_VWA_FIDELITY

EXACT_VWA_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "exact.vwa-classifieds.released.v1",
    canonical_digest(
        {
            "agent_type": EXACT_VWA_FIDELITY.agent_type,
            "policy_model": EXACT_VWA_FIDELITY.policy_model,
            "value_model": EXACT_VWA_FIDELITY.value_model,
            "rlm_model": EXACT_VWA_FIDELITY.reflective_language_model,
            "embedding_model": EXACT_VWA_FIDELITY.embedding_model,
            "max_depth": EXACT_VWA_FIDELITY.max_depth,
            "max_steps": EXACT_VWA_FIDELITY.max_environment_steps,
            "branching_factor": EXACT_VWA_FIDELITY.branching_factor,
            "vf_budget": EXACT_VWA_FIDELITY.value_function_budget,
            "time_budget_minutes_per_step": EXACT_VWA_FIDELITY.time_budget_minutes_per_step,
            "policy_reflections": EXACT_VWA_FIDELITY.max_reflections_per_task,
            "reflection_threshold": EXACT_VWA_FIDELITY.reflection_threshold,
            "puct": EXACT_VWA_FIDELITY.puct,
            "value_method": EXACT_VWA_FIDELITY.value_function_method,
            "value_reflections": EXACT_VWA_FIDELITY.value_max_reflections_per_task,
            "parallel_workers": EXACT_VWA_FIDELITY.released_parallel_workers,
            "tasks_per_script": EXACT_VWA_FIDELITY.tasks_per_script,
            "tasks_per_environment_reset": EXACT_VWA_FIDELITY.tasks_per_environment_reset,
            "environment_branch_strategy": EXACT_VWA_FIDELITY.environment_branch_strategy,
        }
    ),
)


def build_exact_vwa_classifieds_study(benchmark: BenchmarkTaskSet) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != VISUALWEBARENA_BENCHMARK_ID:
        raise ValueError("ExACT study requires a VisualWebArena benchmark cut")
    split_id = visualwebarena_site_split_id("classifieds")
    benchmark.selected_tasks(split_id)
    return Study(
        project_id="exact-vwa-reproduction",
        study_id="exact-vwa-classifieds-released",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="agent",
            kind="agent",
            implementation="exact",
            treatment="rmcts-mad",
            capabilities=("environment.act", "environment.reset"),
            configurations=(
                "exact.vwa.search",
                "exact.vwa.policy-prompt",
                "exact.vwa.value-prompt",
                "exact.vwa.reflection-prompt",
                "exact.vwa.model-roles",
                "exact.vwa.reset-orchestration",
            ),
        ),
        models={
            "policy": StudyModel(
                "model.exact.policy",
                prompt="exact.vwa.policy-prompt",
            ),
            "value": StudyModel(
                "model.exact.value",
                prompt="exact.vwa.value-prompt",
            ),
            "reflection": StudyModel(
                "model.exact.reflection",
                prompt="exact.vwa.reflection-prompt",
            ),
            "embedding": "model.exact.embedding",
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="visualwebarena",
            ),
            MeasurementDefinition.scalar(
                "environment_steps",
                schema_id="noetrium.measurement.count.v1",
                unit="step",
                semantic_kind="resource_usage",
                scale="count",
                domain="visualwebarena",
            ),
        ),
        trial=EXACT_VWA_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=("released-default",),
        limits=TrialBudget(
            "exact-vwa-5-env-steps",
            max_steps=EXACT_VWA_FIDELITY.max_environment_steps,
            max_seconds=(
                EXACT_VWA_FIDELITY.max_environment_steps
                * EXACT_VWA_FIDELITY.time_budget_minutes_per_step
                * 60.0
            ),
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()



__all__ = ["EXACT_VWA_TRIAL_PROTOCOL", "build_exact_vwa_classifieds_study"]
