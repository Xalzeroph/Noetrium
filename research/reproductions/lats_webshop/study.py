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
from research.benchmarks.webshop import LATS_WEBSHOP_SPLIT, WEBSHOP_BENCHMARK_ID

from .fidelity import LATS_WEBSHOP_FIDELITY

LATS_WEBSHOP_RELEASED_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "lats.webshop.released.v1",
    canonical_digest(
        {
            "model": LATS_WEBSHOP_FIDELITY.reference_model,
            "temperature": LATS_WEBSHOP_FIDELITY.temperature,
            "iterations": LATS_WEBSHOP_FIDELITY.max_iterations,
            "tree_depth": LATS_WEBSHOP_FIDELITY.max_tree_depth,
            "rollout_candidates": LATS_WEBSHOP_FIDELITY.rollout_candidate_count,
            "value_samples": LATS_WEBSHOP_FIDELITY.value_evaluation_sample_count,
            "uct_c": LATS_WEBSHOP_FIDELITY.uct_exploration_constant,
            "requires_branchable_environment": LATS_WEBSHOP_FIDELITY.requires_branchable_environment_state,
        }
    ),
)


def build_lats_webshop_released_study(benchmark: BenchmarkTaskSet) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != WEBSHOP_BENCHMARK_ID:
        raise ValueError("LATS study requires the released WebShop benchmark cut")
    benchmark.selected_tasks(LATS_WEBSHOP_SPLIT)
    return Study(
        project_id="lats-webshop-reproduction",
        study_id="lats-webshop-released",
        benchmark=benchmark,
        benchmark_split_id=LATS_WEBSHOP_SPLIT,
        method=StudyParticipant(
            role="agent",
            kind="agent",
            implementation="lats",
            treatment="released-webshop",
            capabilities=("environment.reset", "environment.branch-state"),
            configurations=(
                "lats.webshop.search",
                "lats.webshop.prompt",
                "lats.webshop.value-prompt",
                "lats.webshop.reflection-prompt",
                "lats.webshop.model-roles",
            ),
        ),
        models={
            "policy": StudyModel(
                "model.lats.agent",
                prompt="lats.webshop.prompt",
            ),
            "value": StudyModel(
                "model.lats.value",
                prompt="lats.webshop.value-prompt",
            ),
            "reflection": StudyModel(
                "model.lats.reflection",
                prompt="lats.webshop.reflection-prompt",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "reward",
                schema_id="noetrium.measurement.scalar.v1",
                unit="score",
                semantic_kind="task_reward",
                scale="continuous",
                domain="webshop",
            ),
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="webshop",
            ),
            MeasurementDefinition.scalar(
                "iteration_count",
                schema_id="noetrium.measurement.count.v1",
                unit="iteration",
                semantic_kind="resource_usage",
                scale="count",
                domain="webshop",
            ),
        ),
        trial=LATS_WEBSHOP_RELEASED_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=("paper-default",),
        limits=TrialBudget(
            "lats-webshop-30-iterations",
            max_steps=25000,
            max_turns=LATS_WEBSHOP_FIDELITY.max_iterations,
            max_model_calls=5000,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()



__all__ = ["LATS_WEBSHOP_RELEASED_TRIAL_PROTOCOL", "build_lats_webshop_released_study"]
