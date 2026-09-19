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
from research.benchmarks.flow_practical_tasks import (
    FLOW_PRACTICAL_BENCHMARK_ID,
    FLOW_PRACTICAL_SPLIT_ID,
)

from .fidelity import FLOW_FIDELITY
from .program import FLOW_METHOD_PROGRAM


FLOW_ICLR2025_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "flow.iclr2025.three-designed-tasks.v1",
    canonical_digest({
        "program_digest": FLOW_METHOD_PROGRAM.program_digest,
        "source_commit": FLOW_FIDELITY.audited_commit,
        "candidate_graphs": FLOW_FIDELITY.candidate_graphs,
        "refine_threshold": FLOW_FIDELITY.refine_threshold,
        "max_refine_iterations": FLOW_FIDELITY.max_refine_iterations,
        "max_validation_iterations": FLOW_FIDELITY.max_validation_iterations,
        "paper_execution": "concurrent-ready-set",
        "paper_refinement_strategy": "wait-for-active-tasks-then-update",
        "quantitative_metric": "success_rate",
        "qualitative_metric": "human_rating_1_to_4",
        "human_rater_count": 50,
        "trial_repetitions": 5,
        "published_seed_schedule": False,
    }),
)


def build_flow_iclr2025_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != FLOW_PRACTICAL_BENCHMARK_ID:
        raise ValueError("Flow study requires the paper-native practical-task cut")
    selected = benchmark.selected_tasks(FLOW_PRACTICAL_SPLIT_ID)
    if len(selected) != 3:
        raise ValueError("Flow ICLR 2025 protocol requires all three designed tasks")

    return Study(
        project_id="flow-iclr2025-reproduction",
        study_id="flow-three-designed-tasks",
        benchmark=benchmark,
        benchmark_split_id=FLOW_PRACTICAL_SPLIT_ID,
        method=StudyParticipant(
            role="flow",
            kind="multi_agent_workflow",
            implementation="flow-modularized-agentic-workflow",
            treatment="dynamic-aov-refinement",
            configurations=(
                "flow.iclr2025.aov",
                "flow.iclr2025.validation",
                "flow.iclr2025.lazy-refinement",
            ),
        ),
        models={
            "initializer": StudyModel(
                "model.flow.initializer",
                prompt="flow.iclr2025.initialize-workflow",
            ),
            "executor": StudyModel(
                "model.flow.executor",
                prompt="flow.iclr2025.execute-subtask",
            ),
            "validator": StudyModel(
                "model.flow.validator",
                prompt="flow.iclr2025.validate-subtask",
            ),
            "refiner": StudyModel(
                "model.flow.refiner",
                prompt="flow.iclr2025.update-workflow",
            ),
            "summary": StudyModel(
                "model.flow.summary",
                prompt="flow.iclr2025.summary",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="flow-practical-tasks",
            ),
            MeasurementDefinition.scalar(
                "human_rating",
                schema_id="noetrium.measurement.scalar.v1",
                unit="score",
                semantic_kind="human_satisfaction",
                scale="ordinal",
                domain="flow-practical-tasks",
            ),
            MeasurementDefinition.scalar(
                "subtask_count",
                schema_id="noetrium.measurement.count.v1",
                unit="subtask",
                semantic_kind="workflow_size",
                scale="count",
                domain="flow-practical-tasks",
            ),
            MeasurementDefinition.scalar(
                "refinement_count",
                schema_id="noetrium.measurement.count.v1",
                unit="refinement",
                semantic_kind="workflow_adaptation",
                scale="count",
                domain="flow-practical-tasks",
            ),
            MeasurementDefinition.scalar(
                "task_execution_count",
                schema_id="noetrium.measurement.count.v1",
                unit="execution",
                semantic_kind="execution_effort",
                scale="count",
                domain="flow-practical-tasks",
            ),
        ),
        trial=FLOW_ICLR2025_TRIAL_PROTOCOL,
        repetitions=5,
        seeds=(
            "paper-trial-1",
            "paper-trial-2",
            "paper-trial-3",
            "paper-trial-4",
            "paper-trial-5",
        ),
        limits=TrialBudget(
            "flow-iclr2025-paper-tasks",
            max_steps=1024,
            max_turns=512,
            max_model_calls=1024,
            max_working_seconds=14400.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "FLOW_ICLR2025_TRIAL_PROTOCOL",
    "build_flow_iclr2025_study",
]
