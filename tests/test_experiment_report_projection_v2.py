from __future__ import annotations

import pytest

from noetrium_platform.research.experimentation.experiment.api import (
    ExecutionMode, ExperimentDefinition, ExperimentLifecycleState, ExperimentUnit,
    ExperimentUnitKind, ObservationEnvelope, ObservationKind, UnitOutcome, UnitOutcomeState,
)
from noetrium_platform.research.experimentation.study.runtime import (
    UniversalExperimentKernel, project_experiment_run_report,
)

SHA = "a" * 64

def definition() -> ExperimentDefinition:
    return ExperimentDefinition(
        "project", "experiment", "protocol", ExperimentUnitKind.EPISODE,
        ExecutionMode.SIMULATION, SHA, "b" * 64, "c" * 64, "d" * 64, "e" * 64,
    )

def unit(unit_id: str, ordinal: int) -> ExperimentUnit:
    return ExperimentUnit(unit_id, ExperimentUnitKind.EPISODE, SHA, "b" * 64, "seed", ordinal=ordinal)

def observation(unit_id: str, sequence: int = 0) -> ObservationEnvelope:
    return ObservationEnvelope(
        "experiment", "run-1", unit_id, sequence, f"t{sequence}", "simulator",
        "episode.v1", ObservationKind.TRAJECTORY, {"return": 1.0},
    )

def test_report_projection_consumes_committed_facts_without_executing_units() -> None:
    plan = UniversalExperimentKernel().compile(definition(), (unit("episode-a", 0), unit("episode-b", 1)))
    outcomes = (
        UnitOutcome("episode-a", UnitOutcomeState.SUCCEEDED, 1, (observation("episode-a").observation_digest,)),
        UnitOutcome("episode-b", UnitOutcomeState.SUCCEEDED, 1, (observation("episode-b").observation_digest,)),
    )
    report = project_experiment_run_report(
        plan, "run-1", outcomes, (observation("episode-a"), observation("episode-b"))
    )
    assert report.state is ExperimentLifecycleState.COMPLETED
    assert report.outcomes == outcomes
    assert report.findings == ()

def test_report_projection_derives_partial_from_committed_outcomes() -> None:
    plan = UniversalExperimentKernel().compile(definition(), (unit("episode-a", 0), unit("episode-b", 1)))
    outcomes = (
        UnitOutcome("episode-a", UnitOutcomeState.SUCCEEDED, 1, (observation("episode-a").observation_digest,)),
        UnitOutcome("episode-b", UnitOutcomeState.FAILED, 1, error_code="executor.RuntimeError"),
    )
    report = project_experiment_run_report(plan, "run-2", outcomes, (observation("episode-a"),))
    assert report.state is ExperimentLifecycleState.PARTIAL
    assert report.outcomes[1].error_code == "executor.RuntimeError"

def test_report_projection_rejects_non_plan_outcome_order() -> None:
    plan = UniversalExperimentKernel().compile(definition(), (unit("episode-a", 0), unit("episode-b", 1)))
    outcomes = (
        UnitOutcome("episode-b", UnitOutcomeState.SUCCEEDED, 1),
        UnitOutcome("episode-a", UnitOutcomeState.SUCCEEDED, 1),
    )
    with pytest.raises(ValueError, match="planned unit order"):
        project_experiment_run_report(plan, "run-3", outcomes, ())

def test_doctor_findings_can_make_an_otherwise_successful_cut_partial() -> None:
    plan = UniversalExperimentKernel().compile(definition(), (unit("episode-a", 0),))
    outcomes = (UnitOutcome("episode-a", UnitOutcomeState.SUCCEEDED, 1),)
    late = observation("episode-a", sequence=1)
    report = project_experiment_run_report(plan, "run-4", outcomes, (late,))
    assert report.state is ExperimentLifecycleState.PARTIAL
    assert any(item.code == "observation.sequence_gap" for item in report.findings)
