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
from research.benchmarks.alfworld import (
    ALFWORLD_BENCHMARK_ID,
    ALFWORLD_QLASS_DEV_EXPECTED_TASK_COUNT,
    ALFWORLD_QLASS_DEV_LAUNCHER_SPLIT,
    ALFWORLD_QLASS_DEV_REVISION,
    ALFWORLD_QLASS_DEV_SPLIT,
)

from .fidelity import QLASS_ALFWORLD_RELEASED_FIDELITY

QLASS_ALFWORLD_RELEASED_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "qlass.alfworld.later-released-code.v1",
    canonical_digest(
        {
            "benchmark_revision": ALFWORLD_QLASS_DEV_REVISION,
            "launcher_split": ALFWORLD_QLASS_DEV_LAUNCHER_SPLIT,
            "provider_split": ALFWORLD_QLASS_DEV_SPLIT,
            "base_model": QLASS_ALFWORLD_RELEASED_FIDELITY.base_model,
            "model_roles": [
                QLASS_ALFWORLD_RELEASED_FIDELITY.policy_role,
                QLASS_ALFWORLD_RELEASED_FIDELITY.q_value_role,
            ],
            "best_of_n": QLASS_ALFWORLD_RELEASED_FIDELITY.best_of_n,
            "num_icl_examples": QLASS_ALFWORLD_RELEASED_FIDELITY.num_icl_examples,
            "trajectories_per_task": QLASS_ALFWORLD_RELEASED_FIDELITY.trajectories_per_task,
            "max_turns_per_trajectory": QLASS_ALFWORLD_RELEASED_FIDELITY.max_turns_per_trajectory,
            "sampling_mode": QLASS_ALFWORLD_RELEASED_FIDELITY.sampling_mode,
            "seed": QLASS_ALFWORLD_RELEASED_FIDELITY.random_seed,
            "branch_strategy": QLASS_ALFWORLD_RELEASED_FIDELITY.branch_strategy,
        }
    ),
)


def build_qlass_alfworld_later_released_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != ALFWORLD_BENCHMARK_ID:
        raise ValueError("QLASS released study requires ALFWorld")
    if benchmark.revision_id != ALFWORLD_QLASS_DEV_REVISION:
        raise ValueError("QLASS released study requires its 140-task ALFWorld dev cut")
    selected = benchmark.selected_tasks(ALFWORLD_QLASS_DEV_SPLIT)
    if len(selected) != ALFWORLD_QLASS_DEV_EXPECTED_TASK_COUNT:
        raise ValueError("QLASS released ALFWorld dev lane requires all 140 tasks")

    return Study(
        project_id="qlass-reproduction",
        study_id="qlass-alfworld-later-released",
        benchmark=benchmark,
        benchmark_split_id=ALFWORLD_QLASS_DEV_SPLIT,
        method=StudyParticipant(
            role="agent",
            kind="agent",
            implementation="qlass",
            treatment="q-guided-best-of-n",
            capabilities=("environment.reset", "environment.branch-state"),
            configurations=(
                "qlass.alfworld.prompt",
                "qlass.alfworld.q-guided-search",
                "qlass.alfworld.replay",
                "qlass.alfworld.model-roles",
            ),
        ),
        models={
            "policy": StudyModel(
                "model.qlass.sft-policy",
                prompt="qlass.alfworld.prompt",
            ),
            "q_value": "model.qlass.q-net",
        },
        measurements=(
            MeasurementDefinition.scalar(
                "trajectory_reward",
                schema_id="noetrium.measurement.scalar.v1",
                unit="score",
                semantic_kind="task_reward",
                scale="continuous",
                domain="alfworld",
            ),
            MeasurementDefinition.scalar(
                "trajectory_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="alfworld",
            ),
            MeasurementDefinition.scalar(
                "first_trajectory_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="first_inference_success",
                scale="binary",
                domain="alfworld",
            ),
            MeasurementDefinition.scalar(
                "committed_turns",
                schema_id="noetrium.measurement.count.v1",
                unit="turn",
                semantic_kind="resource_usage",
                scale="count",
                domain="alfworld",
            ),
        ),
        trial=QLASS_ALFWORLD_RELEASED_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=("42",),
        limits=TrialBudget(
            "qlass-alfworld-3x40-committed-turns",
            max_steps=4096,
            max_turns=QLASS_ALFWORLD_RELEASED_FIDELITY.committed_turn_budget,
            max_model_calls=(
                QLASS_ALFWORLD_RELEASED_FIDELITY.committed_turn_budget
                * (QLASS_ALFWORLD_RELEASED_FIDELITY.best_of_n + 1)
            ),
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()

__all__ = [
    "QLASS_ALFWORLD_RELEASED_TRIAL_PROTOCOL",
    "build_qlass_alfworld_later_released_study",
]
