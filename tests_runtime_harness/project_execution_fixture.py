from __future__ import annotations

from noetrium import api


def build_study() -> api.research_authoring.ResearchStudyDefinition:
    task = api.research_authoring.TaskDefinition(
        "task-1",
        "1",
        "fixture",
        "task.fixture.v1",
        api.research_authoring.canonical_digest({"task": "fixture"}),
    )
    benchmark = api.research_authoring.BenchmarkTaskSet(
        "fixture-benchmark",
        "1",
        api.research_authoring.canonical_digest({"source": "fixture"}),
        "task.fixture.v1",
        (task,),
    )
    measurement = api.research_authoring.MeasurementDefinition.scalar(
        "success",
        schema_id="measurement.boolean.v1",
        semantic_kind="task_success",
        scale="binary",
    )
    return api.research_authoring.Study(
        project_id="fixture-project",
        study_id="fixture-study",
        benchmark=benchmark,
        method=api.research_authoring.StudyParticipant(
            "agent",
            "agent",
            "fixture-method",
            "fixture-treatment",
        ),
        models={},
        measurements=(measurement,),
        trial=api.research_authoring.ExperimentTrialProtocolIdentity(
            "fixture-trial",
            "7" * 64,
        ),
        repetitions=1,
        seeds=("seed-1",),
        limits=api.research_authoring.TrialBudget("fixture-budget", max_steps=1),
    ).build()


__all__ = ["build_study"]
