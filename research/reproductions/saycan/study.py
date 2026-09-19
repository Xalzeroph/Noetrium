from __future__ import annotations

from enum import StrEnum

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
from research.benchmarks.saycan_101 import (
    SAYCAN_ALL_SPLIT,
    SAYCAN_BENCHMARK_ID,
    SAYCAN_DATA_COMMIT,
    SAYCAN_TASK_COUNT,
)

from .fidelity import SAYCAN_FIDELITY
from .program import SAYCAN_METHOD_PROGRAM
from .source import SAYCAN_PAPER_CODE_COMMIT


class SayCanEvaluationScene(StrEnum):
    MOCK_KITCHEN = "mock_kitchen"
    REAL_KITCHEN = "real_kitchen"


def saycan_corl2022_trial_protocol(
    benchmark: BenchmarkTaskSet,
    *,
    scene: SayCanEvaluationScene,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != SAYCAN_BENCHMARK_ID:
        raise ValueError("SayCan protocol requires canonical SayCan-101 benchmark")
    if not isinstance(scene, SayCanEvaluationScene):
        raise TypeError("SayCan scene must be SayCanEvaluationScene")
    selected = benchmark.selected_tasks(SAYCAN_ALL_SPLIT)
    if len(selected) != SAYCAN_TASK_COUNT:
        raise ValueError("SayCan protocol requires exactly 101 tasks")
    return ExperimentTrialProtocolIdentity(
        f"saycan.corl2022.{scene.value}.101.v1",
        canonical_digest({
            "paper_code_commit": SAYCAN_PAPER_CODE_COMMIT,
            "evaluation_data_commit": SAYCAN_DATA_COMMIT,
            "benchmark_cut_digest": benchmark.cut_digest,
            "benchmark_split_id": SAYCAN_ALL_SPLIT,
            "task_count": len(selected),
            "method_program_digest": SAYCAN_METHOD_PROGRAM.program_digest,
            "scene": scene.value,
            "planning_semantics": {
                "language_transform": SAYCAN_FIDELITY.language_score_transform,
                "combined_score_rule": SAYCAN_FIDELITY.combined_score_rule,
                "selection_rule": SAYCAN_FIDELITY.selection_rule,
                "termination_string": SAYCAN_FIDELITY.termination_string,
                "termination_affordance": SAYCAN_FIDELITY.termination_affordance,
            },
            "plan_success_verifier": {
                "judge_count": 3,
                "required_positive_votes": 2,
                "semantic": "human-plan-validity",
            },
            "execution_success_verifier": {
                "judge_count": 3,
                "required_positive_votes": 2,
                "semantic": "human-task-achievement",
            },
        }),
    )


def build_saycan_corl2022_study(
    benchmark: BenchmarkTaskSet,
    *,
    scene: SayCanEvaluationScene = SayCanEvaluationScene.MOCK_KITCHEN,
) -> ResearchStudyDefinition:
    protocol = saycan_corl2022_trial_protocol(
        benchmark,
        scene=scene,
    )
    return Study(
        project_id="saycan-corl-2022-reproduction",
        study_id=f"saycan-corl-2022-{scene.value}-101",
        benchmark=benchmark,
        benchmark_split_id=SAYCAN_ALL_SPLIT,
        method=StudyParticipant(
            role="language_affordance_embodied_planner",
            kind="method",
            implementation="saycan",
            treatment="corl-2022-protocol",
            capabilities=(
                "environment.embodied",
                "model.text.score",
                "participant.capability",
                "evaluation.human-majority",
            ),
            configurations=(
                "saycan.language-affordance-product",
                "saycan.done-termination",
                "saycan.plan-before-execute",
                f"saycan.scene-{scene.value}",
            ),
        ),
        models={
            "language": StudyModel(
                "model.saycan.paper-era-language-model",
                prompt="saycan.skill-selection.prompt",
            ),
            "affordance": StudyModel(
                "model.saycan.paper-era-affordance-value",
                prompt="saycan.affordance-estimator",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "plan_success",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="human_majority_plan_success",
                scale="binary",
                domain="saycan",
            ),
            MeasurementDefinition.scalar(
                "execution_success",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="human_majority_task_execution_success",
                scale="binary",
                domain="saycan",
            ),
            MeasurementDefinition.scalar(
                "planning_calls",
                schema_id="noetrium.measurement.count.v1",
                unit="model_call",
                semantic_kind="saycan_planning_calls",
                scale="count",
                domain="saycan",
            ),
            MeasurementDefinition.scalar(
                "executed_skill_count",
                schema_id="noetrium.measurement.count.v1",
                unit="skill",
                semantic_kind="saycan_executed_skill_count",
                scale="count",
                domain="saycan",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("published-evaluation-cut",),
        limits=TrialBudget(
            f"saycan-corl2022-{scene.value}-budget",
            max_steps=256,
            max_turns=SAYCAN_FIDELITY.demo_max_tasks,
            max_model_calls=SAYCAN_FIDELITY.demo_max_tasks,
            max_working_seconds=1800.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=1800.0,
    ).build()


__all__ = [
    "SayCanEvaluationScene",
    "build_saycan_corl2022_study",
    "saycan_corl2022_trial_protocol",
]
