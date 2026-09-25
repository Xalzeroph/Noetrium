from __future__ import annotations

from noetrium import api


def build_study() -> api.ResearchStudyDefinition:
    task = api.TaskDefinition(
        "task-1",
        "1",
        "fixture",
        "task.fixture.v1",
        api.canonical_digest({"task": "fixture"}),
    )
    benchmark = api.BenchmarkTaskSet(
        "fixture-benchmark",
        "1",
        api.canonical_digest({"source": "fixture"}),
        "task.fixture.v1",
        (task,),
    )
    measurement = api.MeasurementDefinition.scalar(
        "success",
        schema_id="measurement.boolean.v1",
        semantic_kind="task_success",
        scale="binary",
    )
    return api.Study(
        project_id="fixture-project",
        study_id="fixture-study",
        benchmark=benchmark,
        method=api.StudyParticipant(
            "agent",
            "agent",
            "fixture-method",
            "fixture-treatment",
        ),
        models={},
        measurements=(measurement,),
        trial=api.ExperimentTrialProtocolIdentity(
            "fixture-trial",
            "7" * 64,
        ),
        repetitions=1,
        seeds=("seed-1",),
        limits=api.TrialBudget("fixture-budget", max_steps=1),
    ).build()


__all__ = ["build_study"]
