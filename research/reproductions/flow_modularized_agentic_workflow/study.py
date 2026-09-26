from __future__ import annotations
from research.reproductions import _support as _rs
from research.benchmarks.flow_practical_tasks import (
    FLOW_PRACTICAL_BENCHMARK_ID,
    FLOW_PRACTICAL_SPLIT_ID,
)

from .fidelity import FLOW_FIDELITY
from .program import FLOW_METHOD_PROGRAM


FLOW_ICLR2025_TRIAL_PROTOCOL = _rs.study_protocol(
    "flow.iclr2025.three-designed-tasks.v1",
    _rs.canonical_digest({
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


@_rs.study_factory('benchmark')
def build_flow_iclr2025_study(
    benchmark,
):
    if benchmark.benchmark_id != FLOW_PRACTICAL_BENCHMARK_ID:
        raise ValueError("Flow study requires the paper-native practical-task cut")
    selected = benchmark.selected_tasks(FLOW_PRACTICAL_SPLIT_ID)
    if len(selected) != 3:
        raise ValueError("Flow ICLR 2025 protocol requires all three designed tasks")

    return _rs.study_spec(project_id="flow-iclr2025-reproduction",
        study_id="flow-three-designed-tasks",
        benchmark=benchmark,
        benchmark_split_id=FLOW_PRACTICAL_SPLIT_ID,
        method=_rs.study_participant(
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
            "initializer": _rs.study_model(
                "model.flow.initializer",
                prompt="flow.iclr2025.initialize-workflow",
            ),
            "executor": _rs.study_model(
                "model.flow.executor",
                prompt="flow.iclr2025.execute-subtask",
            ),
            "validator": _rs.study_model(
                "model.flow.validator",
                prompt="flow.iclr2025.validate-subtask",
            ),
            "refiner": _rs.study_model(
                "model.flow.refiner",
                prompt="flow.iclr2025.update-workflow",
            ),
            "summary": _rs.study_model(
                "model.flow.summary",
                prompt="flow.iclr2025.summary",
            ),
        },
        measurements=(
            _rs.scalar_measurement(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="flow-practical-tasks",
            ),
            _rs.scalar_measurement(
                "human_rating",
                schema_id="noetrium.measurement.scalar.v1",
                unit="score",
                semantic_kind="human_satisfaction",
                scale="ordinal",
                domain="flow-practical-tasks",
            ),
            _rs.scalar_measurement(
                "subtask_count",
                schema_id="noetrium.measurement.count.v1",
                unit="subtask",
                semantic_kind="workflow_size",
                scale="count",
                domain="flow-practical-tasks",
            ),
            _rs.scalar_measurement(
                "refinement_count",
                schema_id="noetrium.measurement.count.v1",
                unit="refinement",
                semantic_kind="workflow_adaptation",
                scale="count",
                domain="flow-practical-tasks",
            ),
            _rs.scalar_measurement(
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
        limits=_rs.trial_budget(
            "flow-iclr2025-paper-tasks",
            max_steps=1024,
            max_turns=512,
            max_model_calls=1024,
            max_working_seconds=14400.0,
        ),
        replay_level='observational',
    )


__all__ = [
    "FLOW_ICLR2025_TRIAL_PROTOCOL",
    "build_flow_iclr2025_study",
]
