from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentTrialProtocolIdentity,
)
from noetrium_platform.research.experimentation.identity import ModelRoleUsage, ReplayLevel
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    FactorLevelSpec,
    MeasurementDefinition,
    Study,
    StudyFactorSpec,
    StudyModel,
    StudyParticipant,
    TaskDefinition,
    TaskSetSplit,
    TrialBudget,
)


def _benchmark() -> BenchmarkTaskSet:
    tasks = (
        TaskDefinition("task-a", "1", "family-a", "task.v1", canonical_digest({"task": "a"})),
        TaskDefinition("task-b", "1", "family-b", "task.v1", canonical_digest({"task": "b"})),
    )
    return BenchmarkTaskSet(
        "benchmark",
        "1",
        canonical_digest({"source": "benchmark"}),
        "task.v1",
        tasks,
        splits=(TaskSetSplit("eval", ("task-b", "task-a")),),
    )


def _success() -> MeasurementDefinition:
    return MeasurementDefinition.scalar(
        "success",
        schema_id="measurement.boolean.v1",
        semantic_kind="task_success",
        scale="binary",
    )


def test_declarative_study_lowers_to_internal_typed_protocol() -> None:
    study = Study(
        project_id="react-reproduction",
        study_id="react-alfworld",
        benchmark=_benchmark(),
        benchmark_split_id="eval",
        method=StudyParticipant(
            role="agent",
            kind="agent",
            implementation="react",
            treatment="released-code",
            capabilities=("environment.act",),
            configurations=("react.prompt",),
        ),
        models={
            "action": StudyModel(
                "model.react.action",
                prompt="react.prompt",
            )
        },
        measurements=(_success(),),
        trial=ExperimentTrialProtocolIdentity("trial.react", "3" * 64),
        repetitions=3,
        seeds=("seed-1",),
        limits=TrialBudget("react-limits", max_turns=49, max_tokens=100_000),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()

    assert study.project_id == "react-reproduction"
    assert study.experiment_id == study.study_id == "react-alfworld"
    assert study.repetitions == 3
    assert study.execution_policy.trial_budget.max_turns == 49
    participant = study.binding_requirements.participants[0]
    assert participant.role == "agent"
    assert participant.method_id == "react"
    assert participant.capability_requirement_ids == ("environment.act",)
    action = study.binding_requirements.model_role("action")
    assert action.requirement_id == "model.react.action"
    assert action.prompt_configuration_id == "react.prompt"
    assert action.usage is ModelRoleUsage.EXECUTION
    assert study.measurement_protocol.definition("success").semantic_kind == "task_success"


def test_user_simulator_is_explicit_participant_not_environment_state() -> None:
    study = Study(
        project_id="tau-reproduction",
        study_id="tau-bench",
        benchmark=_benchmark(),
        method=StudyParticipant(
            role="agent",
            kind="agent",
            implementation="tau-agent",
            treatment="policy",
        ),
        participants=(
            StudyParticipant(
                role="user",
                kind="user_simulator",
                implementation="tau-user-simulator",
                treatment="default-user",
                depends_on=("agent",),
            ),
        ),
        models={
            "agent": "model.tau.agent",
            "user": "model.tau.user",
            "grader": StudyModel(
                "model.tau.grader",
                usage=ModelRoleUsage.EVALUATION,
            ),
        },
        measurements=(_success(),),
        trial=ExperimentTrialProtocolIdentity("trial.tau", "4" * 64),
        repetitions=1,
        seeds=("seed-1",),
        limits=TrialBudget("tau-limits", max_turns=30),
    ).build()

    assert tuple(row.role for row in study.binding_requirements.participants) == (
        "agent",
        "user",
    )
    assert study.binding_requirements.participants[1].participant_kind == "user_simulator"
    assert study.binding_requirements.model_role("user").requirement_id == "model.tau.user"
    assert study.binding_requirements.model_role("grader").usage is ModelRoleUsage.EVALUATION


def test_declarative_study_canonicalizes_author_declaration_order() -> None:
    factor_a = StudyFactorSpec(
        "factor-a",
        (
            FactorLevelSpec("a-control", "a0", control=True),
            FactorLevelSpec("a1", "a1"),
        ),
    )
    factor_z = StudyFactorSpec(
        "factor-z",
        (
            FactorLevelSpec("z-control", "z0", control=True),
            FactorLevelSpec("z1", "z1"),
        ),
    )
    participant_a = StudyParticipant(
        "a-role", "agent", "method-a", "treatment"
    )
    participant_z = StudyParticipant(
        "z-role", "agent", "method-z", "treatment"
    )

    def build(reverse: bool):
        factors = (factor_z, factor_a) if not reverse else (factor_a, factor_z)
        extras = (participant_z,) if not reverse else (participant_a,)
        method = participant_a if not reverse else participant_z
        measurements = (
            MeasurementDefinition.scalar("z-metric", schema_id="metric.z.v1"),
            MeasurementDefinition.scalar("a-metric", schema_id="metric.a.v1"),
        )
        if reverse:
            measurements = tuple(reversed(measurements))
        return Study(
            project_id="project",
            study_id="study",
            benchmark=_benchmark(),
            benchmark_split_id="eval",
            method=method,
            participants=extras,
            models={"policy": StudyModel("model", prompt="prompt")},
            measurements=measurements,
            trial=ExperimentTrialProtocolIdentity("trial.protocol", "5" * 64),
            repetitions=2,
            seeds=("seed-1", "seed-2"),
            limits=TrialBudget("budget", max_steps=10, max_tokens=1000),
            replay_level=ReplayLevel.EXACT,
            factors=factors,
        ).build()

    left = build(False)
    right = build(True)
    assert left.definition_digest == right.definition_digest
    assert tuple(row.factor_id for row in left.factors) == ("factor-a", "factor-z")
    assert tuple(row.measurement_id for row in left.measurement_protocol.definitions) == (
        "a-metric",
        "z-metric",
    )
    assert tuple(row.role for row in left.binding_requirements.participants) == (
        "a-role",
        "z-role",
    )


def test_declarative_study_requires_explicit_schedule_measurements_and_limits() -> None:
    common = dict(
        project_id="project",
        study_id="study",
        benchmark=_benchmark(),
        method=StudyParticipant("agent", "agent", "method", "treatment"),
        models={},
        trial=ExperimentTrialProtocolIdentity("trial.protocol", "6" * 64),
        repetitions=1,
        limits=TrialBudget("budget", max_steps=1),
    )
    with pytest.raises(TypeError, match="measurements"):
        Study(measurements=(), seeds=("seed",), **common)
    with pytest.raises(TypeError, match="seeds"):
        Study(measurements=(_success(),), seeds=(), **common)
