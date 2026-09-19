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
from research.benchmarks.math500 import (
    MATH500_BENCHMARK_ID,
    MATH500_EXPECTED_TASK_COUNT,
    MATH500_LITS_REVISION,
    MATH500_TEST_SPLIT,
)

from .fidelity import LITS_MATH500_RELEASE_FIDELITY

LITS_MATH500_RELEASE_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "lits.math500.paper-era-release.v2",
    canonical_digest(
        {
            "benchmark_revision": MATH500_LITS_REVISION,
            "search_algorithm": LITS_MATH500_RELEASE_FIDELITY.search_algorithm,
            "components": {
                "policy": LITS_MATH500_RELEASE_FIDELITY.policy_component,
                "transition": LITS_MATH500_RELEASE_FIDELITY.transition_component,
                "reward": LITS_MATH500_RELEASE_FIDELITY.reward_component,
            },
            "search_iterations": LITS_MATH500_RELEASE_FIDELITY.search_iterations,
            "candidate_actions": LITS_MATH500_RELEASE_FIDELITY.candidate_actions,
            "max_steps": LITS_MATH500_RELEASE_FIDELITY.max_steps,
            "model_binding_semantics": LITS_MATH500_RELEASE_FIDELITY.model_binding_semantics,
        }
    ),
)


def build_lits_math500_release_study(benchmark: BenchmarkTaskSet) -> ResearchStudyDefinition:
    """Compile the source-bound LiTS MATH500 released-code lane.

    This is not labelled a matched paper experiment because the release example
    leaves the concrete LLM provider/model externally configurable.
    """

    if benchmark.benchmark_id != MATH500_BENCHMARK_ID or benchmark.revision_id != MATH500_LITS_REVISION:
        raise ValueError("LiTS release study requires its source-bound MATH500 cut")
    if len(benchmark.selected_tasks(MATH500_TEST_SPLIT)) != MATH500_EXPECTED_TASK_COUNT:
        raise ValueError("LiTS MATH500 lane requires all 500 test tasks")

    return Study(
        project_id="lits-reproduction",
        study_id="lits-math500-paper-era-release",
        benchmark=benchmark,
        benchmark_split_id=MATH500_TEST_SPLIT,
        method=StudyParticipant(
            role="reasoner",
            kind="agent",
            implementation="lits",
            treatment="mcts-concat-generative",
            configurations=(
                "lits.math500.policy.concat",
                "lits.math500.transition.concat",
                "lits.math500.reward.generative",
                "lits.math500.search.mcts",
            ),
        ),
        models={
            "policy": "model.lits.policy",
            "reward": "model.lits.reward",
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_accuracy",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_correctness",
                scale="binary",
                domain="math500",
            ),
            MeasurementDefinition.scalar(
                "search_iterations",
                schema_id="noetrium.measurement.count.v1",
                unit="iteration",
                semantic_kind="search_compute",
                scale="count",
                domain="math500",
            ),
            MeasurementDefinition.scalar(
                "model_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="call",
                semantic_kind="resource_usage",
                scale="count",
                domain="math500",
            ),
        ),
        trial=LITS_MATH500_RELEASE_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=("paper-era-release-default",),
        limits=TrialBudget(
            "lits-math500-max-depth-10",
            max_steps=LITS_MATH500_RELEASE_FIDELITY.max_steps,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()

__all__ = ["LITS_MATH500_RELEASE_TRIAL_PROTOCOL", "build_lits_math500_release_study"]
