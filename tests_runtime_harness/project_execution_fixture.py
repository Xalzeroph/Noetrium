from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkTaskSet,
    ExperimentTrialProtocolIdentity,
    MeasurementDefinition,
    ResearchStudyDefinition,
    Study,
    StudyParticipant,
    TaskDefinition,
    TrialBudget,
)


def build_study() -> ResearchStudyDefinition:
    task = TaskDefinition(
        "task-1",
        "1",
        "fixture",
        "task.fixture.v1",
        canonical_digest({"task": "fixture"}),
    )
    benchmark = BenchmarkTaskSet(
        "fixture-benchmark",
        "1",
        canonical_digest({"source": "fixture"}),
        "task.fixture.v1",
        (task,),
    )
    measurement = MeasurementDefinition.scalar(
        "success",
        schema_id="measurement.boolean.v1",
        semantic_kind="task_success",
        scale="binary",
    )
    return Study(
        project_id="fixture-project",
        study_id="fixture-study",
        benchmark=benchmark,
        method=StudyParticipant(
            "agent",
            "agent",
            "fixture-method",
            "fixture-treatment",
        ),
        models={},
        measurements=(measurement,),
        trial=ExperimentTrialProtocolIdentity(
            "fixture-trial",
            "7" * 64,
        ),
        repetitions=1,
        seeds=("seed-1",),
        limits=TrialBudget("fixture-budget", max_steps=1),
    ).build()


__all__ = ["build_study"]
