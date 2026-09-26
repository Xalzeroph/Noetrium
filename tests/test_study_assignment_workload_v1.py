from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.api.research_compiler import _assignments
from noetrium_platform.research.experimentation.lifecycle.api import (
    AssignmentWorkload,
    BenchmarkTaskSet,
    ExperimentTrialProtocolIdentity,
    MeasurementDefinition,
    Study,
    StudyParticipant,
    StudyVariantSpec,
    TaskDefinition,
    TaskGraph,
    TaskGraphEdge,
    TaskGraphRelation,
    TaskSetSplit,
    TrialBudget,
    VariantKind,
)


def _benchmark() -> BenchmarkTaskSet:
    revision = "benchmark-workload-v1"
    tasks = (
        TaskDefinition(
            "task:a",
            revision,
            "generic",
            "task.v1",
            canonical_digest({"task": "a"}),
        ),
        TaskDefinition(
            "task:b",
            revision,
            "generic",
            "task.v1",
            canonical_digest({"task": "b"}),
        ),
    )
    return BenchmarkTaskSet(
        "benchmark",
        revision,
        canonical_digest({"benchmark": 1}),
        "task.v1",
        tasks,
        splits=(TaskSetSplit("test", ("task:a", "task:b")),),
        selection_policy_digest=canonical_digest({"selection": "both"}),
    )


def _study(
    assignment_workloads: tuple[AssignmentWorkload, ...] | None = None,
):
    return Study(
        project_id="project",
        study_id="study",
        benchmark=_benchmark(),
        benchmark_split_id="test",
        assignment_workloads=assignment_workloads,
        method=StudyParticipant(
            role="agent",
            kind="agent",
            implementation="method",
            treatment="treatment",
        ),
        models={},
        measurements=(
            MeasurementDefinition.scalar(
                "score",
                schema_id="measurement.scalar.v1",
                unit="ratio",
                semantic_kind="task_score",
                scale="continuous",
                domain="test",
            ),
        ),
        trial=ExperimentTrialProtocolIdentity(
            "trial",
            canonical_digest({"trial": "universal-workload"}),
        ),
        repetitions=1,
        seeds=("seed",),
        limits=TrialBudget("budget", max_steps=1),
    ).build()


def _variant() -> StudyVariantSpec:
    return StudyVariantSpec(
        "control",
        VariantKind.CONTROL,
        "provider",
        canonical_digest({"variant": "control"}),
    )


def test_default_authoring_lowers_each_task_to_one_node_workload() -> None:
    definition = _study()
    assert tuple(
        workload.task_ids for workload in definition.assignment_workloads
    ) == (("task:a",), ("task:b",))

    rows = _assignments(definition, (_variant(),))
    assert tuple(row.workload.task_ids for row in rows) == (
        ("task:a",),
        ("task:b",),
    )


def test_multi_task_chain_is_the_same_assignment_machine() -> None:
    workload = AssignmentWorkload(
        ("task:a", "task:b"),
        TaskGraph(
            (
                TaskGraphEdge(
                    "task:a",
                    "task:b",
                    TaskGraphRelation.PREREQUISITE,
                ),
            )
        ),
    )
    definition = _study((workload,))
    rows = _assignments(definition, (_variant(),))

    assert len(rows) == 1
    assert rows[0].workload == workload
    assert rows[0].workload.dependencies_for("task:a") == ()
    assert rows[0].workload.dependencies_for("task:b") == ("task:a",)
