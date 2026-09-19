from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.api.research_compiler import _assignments
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentTrialProtocolIdentity,
)
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkAssignmentMode,
    BenchmarkTaskSet,
    MeasurementDefinition,
    Study,
    StudyParticipant,
    StudyVariantSpec,
    TaskDefinition,
    TaskSetSplit,
    TrialBudget,
    VariantKind,
)


def _benchmark() -> BenchmarkTaskSet:
    revision = "benchmark-cut-v1"
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


def _study(mode: BenchmarkAssignmentMode):
    return Study(
        project_id="project",
        study_id=f"study-{mode.value}",
        benchmark=_benchmark(),
        benchmark_split_id="test",
        benchmark_assignment_mode=mode,
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
            f"trial-{mode.value}",
            canonical_digest({"mode": mode.value}),
        ),
        repetitions=1,
        seeds=("seed",),
        limits=TrialBudget(f"budget-{mode.value}", max_steps=1),
    ).build()


def _variant() -> StudyVariantSpec:
    return StudyVariantSpec(
        "control",
        VariantKind.CONTROL,
        "provider",
        canonical_digest({"variant": "control"}),
    )


def test_task_assignment_mode_preserves_existing_per_task_expansion() -> None:
    definition = _study(BenchmarkAssignmentMode.TASK)
    rows = _assignments(definition, (_variant(),))
    assert tuple(row.task_id for row in rows) == ("task:a", "task:b")


def test_cut_assignment_mode_runs_one_assignment_over_the_frozen_cut() -> None:
    definition = _study(BenchmarkAssignmentMode.CUT)
    rows = _assignments(definition, (_variant(),))
    assert len(rows) == 1
    assert rows[0].task_id is None
    assert definition.benchmark_assignment_mode is BenchmarkAssignmentMode.CUT
    assert tuple(task.task_id for task in definition.benchmark.selected_tasks("test")) == (
        "task:a",
        "task:b",
    )
