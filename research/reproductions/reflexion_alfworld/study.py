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
from research.benchmarks.alfworld import ALFWORLD_BENCHMARK_ID, ALFWORLD_PAPER_EVAL_SPLIT

from .fidelity import REFLEXION_ALFWORLD_FIDELITY

REFLEXION_ALFWORLD_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "reflexion.alfworld.paper-era.v1",
    canonical_digest(
        {
            "max_trials": REFLEXION_ALFWORLD_FIDELITY.max_trials,
            "max_turns_per_trial": REFLEXION_ALFWORLD_FIDELITY.max_turns_per_trial,
            "action_model": REFLEXION_ALFWORLD_FIDELITY.reference_action_model,
            "reflection_model": REFLEXION_ALFWORLD_FIDELITY.reference_reflection_model,
            "reflection_memory_window": REFLEXION_ALFWORLD_FIDELITY.reflection_memory_window,
            "reflection_after_failed_trial_only": REFLEXION_ALFWORLD_FIDELITY.reflection_after_failed_trial_only,
        }
    ),
)


def build_reflexion_alfworld_study(benchmark: BenchmarkTaskSet) -> ResearchStudyDefinition:
    """Freeze one per-task Reflexion campaign; the ten learning trials stay method-owned."""

    if benchmark.benchmark_id != ALFWORLD_BENCHMARK_ID:
        raise ValueError("Reflexion ALFWorld study requires the shared ALFWorld benchmark cut")
    benchmark.selected_tasks(ALFWORLD_PAPER_EVAL_SPLIT)
    return Study(
        project_id="reflexion-alfworld-reproduction",
        study_id="reflexion-alfworld-paper-era",
        benchmark=benchmark,
        benchmark_split_id=ALFWORLD_PAPER_EVAL_SPLIT,
        method=StudyParticipant(
            role="agent",
            kind="agent",
            implementation="reflexion",
            treatment="verbal-reflection",
            capabilities=("environment.act", "environment.reset"),
            configurations=(
                "reflexion.alfworld.prompt",
                "reflexion.alfworld.reflection-prompt",
                "reflexion.alfworld.model-roles",
            ),
        ),
        models={
            "action": StudyModel(
                "model.reflexion.action",
                prompt="reflexion.alfworld.prompt",
            ),
            "reflection": StudyModel(
                "model.reflexion.reflection",
                prompt="reflexion.alfworld.reflection-prompt",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="alfworld",
            ),
            MeasurementDefinition.scalar(
                "first_success_trial",
                schema_id="noetrium.measurement.count.v1",
                unit="trial",
                semantic_kind="learning_curve",
                scale="count",
                domain="alfworld",
            ),
            MeasurementDefinition.scalar(
                "trials_used",
                schema_id="noetrium.measurement.count.v1",
                unit="trial",
                semantic_kind="resource_usage",
                scale="count",
                domain="alfworld",
            ),
        ),
        trial=REFLEXION_ALFWORLD_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=("42",),
        limits=TrialBudget(
            "reflexion-alfworld-10x49-turn",
            max_steps=8192,
            max_turns=(
                REFLEXION_ALFWORLD_FIDELITY.max_trials
                * REFLEXION_ALFWORLD_FIDELITY.max_turns_per_trial
            ),
            max_model_calls=(
                REFLEXION_ALFWORLD_FIDELITY.max_trials
                * REFLEXION_ALFWORLD_FIDELITY.max_turns_per_trial
                * REFLEXION_ALFWORLD_FIDELITY.action_candidate_attempts
                + REFLEXION_ALFWORLD_FIDELITY.max_trials
            ),
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()



__all__ = ["REFLEXION_ALFWORLD_TRIAL_PROTOCOL", "build_reflexion_alfworld_study"]
