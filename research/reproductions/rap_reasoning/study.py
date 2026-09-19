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
from research.benchmarks.rap_blocksworld import (
    RAP_BLOCKSWORLD_BENCHMARK_ID,
    RAP_BLOCKSWORLD_STEP4_SPLIT,
)

from .fidelity import RAP_FIDELITY

RAP_BLOCKSWORLD_RELEASED_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "rap.blocksworld.released-mcts.v1",
    canonical_digest(
        {
            "model_family": "llama-30b-33b-paper-era",
            "seed": RAP_FIDELITY.seed,
            "temperature": RAP_FIDELITY.temperature,
            "rollouts": RAP_FIDELITY.rollouts,
            "max_depth": RAP_FIDELITY.max_depth,
            "n_sample_confidence": RAP_FIDELITY.n_sample_confidence,
            "alpha": RAP_FIDELITY.alpha,
            "r1_default": RAP_FIDELITY.r1_default,
            "w_exp": RAP_FIDELITY.exploration_weight,
            "discount": RAP_FIDELITY.discount,
            "reasoner_world_model_shared": RAP_FIDELITY.same_llm_reasoner_and_world_model,
            "evaluator": "VAL",
        }
    ),
)


def build_rap_blocksworld_released_study(benchmark: BenchmarkTaskSet) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != RAP_BLOCKSWORLD_BENCHMARK_ID:
        raise ValueError("RAP study requires the released Blocksworld step_4 cut")
    benchmark.selected_tasks(RAP_BLOCKSWORLD_STEP4_SPLIT)
    return Study(
        project_id="rap-blocksworld-reproduction",
        study_id="rap-blocksworld-released-mcts",
        benchmark=benchmark,
        benchmark_split_id=RAP_BLOCKSWORLD_STEP4_SPLIT,
        method=StudyParticipant(
            role="planner",
            kind="agent",
            implementation="rap",
            treatment="mcts-world-model",
            capabilities=("evaluation.plan-validity",),
            configurations=("rap.blocksworld.mcts", "rap.blocksworld.prompt"),
        ),
        models={
            "reasoner": StudyModel(
                "model.rap.reasoner",
                prompt="rap.blocksworld.prompt",
            ),
            "world_model": StudyModel(
                "model.rap.world-model",
                prompt="rap.blocksworld.prompt",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "plan_valid",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="blocksworld",
            ),
            MeasurementDefinition.scalar(
                "rollout_count",
                schema_id="noetrium.measurement.count.v1",
                unit="rollout",
                semantic_kind="resource_usage",
                scale="count",
                domain="blocksworld",
            ),
        ),
        trial=RAP_BLOCKSWORLD_RELEASED_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=(str(RAP_FIDELITY.seed),),
        limits=TrialBudget(
            "rap-blocksworld-10-rollouts",
            max_steps=RAP_FIDELITY.rollouts,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()



__all__ = ["RAP_BLOCKSWORLD_RELEASED_TRIAL_PROTOCOL", "build_rap_blocksworld_released_study"]
