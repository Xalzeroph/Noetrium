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
    VISUALWEBARENA_SITE_TASK_COUNTS,
    visualwebarena_site_split_id,
)

from .fidelity import TREE_SEARCH_VWA_FIDELITY

TREE_SEARCH_VWA_SHOPPING_SPLIT = visualwebarena_site_split_id("shopping")

TREE_SEARCH_VWA_RELEASED_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "tree-search-language-model-agents.vwa-shopping.released.v1",
    canonical_digest(
        {
            "launcher_path": TREE_SEARCH_VWA_FIDELITY.launcher_path,
            "runner_path": TREE_SEARCH_VWA_FIDELITY.runner_path,
            "agent_type": TREE_SEARCH_VWA_FIDELITY.agent_type,
            "search_algorithm": TREE_SEARCH_VWA_FIDELITY.search_algorithm,
            "policy_model": TREE_SEARCH_VWA_FIDELITY.policy_model,
            "value_model": TREE_SEARCH_VWA_FIDELITY.value_model,
            "evaluation_captioner_model": TREE_SEARCH_VWA_FIDELITY.evaluation_captioner_model,
            "temperature": TREE_SEARCH_VWA_FIDELITY.temperature,
            "top_p": TREE_SEARCH_VWA_FIDELITY.top_p,
            "max_steps": TREE_SEARCH_VWA_FIDELITY.max_steps,
            "max_depth": TREE_SEARCH_VWA_FIDELITY.max_depth,
            "branching_factor": TREE_SEARCH_VWA_FIDELITY.branching_factor,
            "value_function_budget": TREE_SEARCH_VWA_FIDELITY.value_function_budget,
            "repeating_action_failure_threshold": TREE_SEARCH_VWA_FIDELITY.repeating_action_failure_threshold,
            "viewport_height": TREE_SEARCH_VWA_FIDELITY.viewport_height,
            "max_observation_length": TREE_SEARCH_VWA_FIDELITY.max_observation_length,
            "action_set_tag": TREE_SEARCH_VWA_FIDELITY.action_set_tag,
            "observation_type": TREE_SEARCH_VWA_FIDELITY.observation_type,
            "prompt_path": TREE_SEARCH_VWA_FIDELITY.prompt_path,
            "environment_branch_strategy": TREE_SEARCH_VWA_FIDELITY.environment_branch_strategy,
        }
    ),
)


def build_tree_search_vwa_shopping_released_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != VISUALWEBARENA_BENCHMARK_ID:
        raise ValueError("Tree Search study requires a VisualWebArena benchmark cut")
    selected = benchmark.selected_tasks(TREE_SEARCH_VWA_SHOPPING_SPLIT)
    if len(selected) != VISUALWEBARENA_SITE_TASK_COUNTS["shopping"]:
        raise ValueError("Tree Search released shopping lane requires all 466 VWA shopping tasks")

    return Study(
        project_id="tree-search-language-model-agents-reproduction",
        study_id="tree-search-vwa-shopping-released",
        benchmark=benchmark,
        benchmark_split_id=TREE_SEARCH_VWA_SHOPPING_SPLIT,
        method=StudyParticipant(
            role="agent",
            kind="agent",
            implementation="tree-search-language-model-agents",
            treatment="released-vwa-shopping-search",
            capabilities=("environment.act", "evaluation.visualwebarena"),
            configurations=(
                "tree-search.vwa-shopping.search",
                "tree-search.vwa-shopping.prompt",
                "tree-search.vwa-shopping.evaluator",
                "tree-search.vwa-shopping.model-roles",
            ),
        ),
        models={
            "policy": StudyModel(
                "model.tree-search.policy",
                prompt="tree-search.vwa-shopping.prompt",
            ),
            "value": "model.tree-search.value",
            "evaluation_captioner": "model.visualwebarena.evaluation-captioner",
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_score",
                schema_id="noetrium.measurement.scalar.v1",
                unit="score",
                semantic_kind="task_score",
                scale="continuous",
                domain="visualwebarena",
            ),
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="visualwebarena",
            ),
            MeasurementDefinition.scalar(
                "committed_steps",
                schema_id="noetrium.measurement.count.v1",
                unit="step",
                semantic_kind="resource_usage",
                scale="count",
                domain="visualwebarena",
            ),
            MeasurementDefinition.scalar(
                "value_evaluations",
                schema_id="noetrium.measurement.count.v1",
                unit="evaluation",
                semantic_kind="search_compute",
                scale="count",
                domain="visualwebarena",
            ),
        ),
        trial=TREE_SEARCH_VWA_RELEASED_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=("paper-default",),
        limits=TrialBudget(
            "tree-search-vwa-shopping-5-committed-steps",
            max_steps=TREE_SEARCH_VWA_FIDELITY.max_steps,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()

__all__ = [
    "TREE_SEARCH_VWA_RELEASED_TRIAL_PROTOCOL",
    "TREE_SEARCH_VWA_SHOPPING_SPLIT",
    "build_tree_search_vwa_shopping_released_study",
]
