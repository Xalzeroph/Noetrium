from __future__ import annotations

from noetrium_platform.research.experimentation.lifecycle.api import (
    AssignmentWorkload,
    StudyAssignment,
    StudyMetricAggregate,
    StudyMetricObservation,
    StudyProtocol,
    StudyVariantSpec,
    VariantKind,
)
from noetrium_platform.research.experimentation.lifecycle.study.algorithms import (
    BasicStudyMetricAggregator,
    DeterministicStudyAssignment,
)
import pytest


def _protocol() -> StudyProtocol:
    return StudyProtocol(
        "study-1",
        "workload-1",
        (
            StudyVariantSpec("control", VariantKind.CONTROL, "memory.fixed", "a" * 64),
            StudyVariantSpec("treatment", VariantKind.TREATMENT, "memory.evolving", "b" * 64),
        ),
        2,
        "c" * 64,
        ("success_rate", "utility"),
        "d" * 64,
        (AssignmentWorkload(("task-1",)),),
        ("standard",),
    )


def test_study_protocol_expands_full_variant_repetition_matrix_and_aggregates():
    protocol = _protocol()
    assignments = DeterministicStudyAssignment().assignments(protocol)
    assert len(assignments) == 4
    observations = tuple(
        StudyMetricObservation(assignment, (("success_rate", 1.0), ("utility", 2.0)))
        for assignment in assignments
    )
    aggregates = BasicStudyMetricAggregator().aggregate(protocol, observations, assignments)
    assert {(item.variant_id, item.metric_name, item.count) for item in aggregates} == {
        ("control", "success_rate", 2),
        ("control", "utility", 2),
        ("treatment", "success_rate", 2),
        ("treatment", "utility", 2),
    }


def test_study_aggregation_is_stable_for_large_baseline_small_variance() -> None:
    protocol = _protocol()
    assignments = DeterministicStudyAssignment().assignments(protocol)
    baseline = 1_000_000_000_000.0
    observations = tuple(
        StudyMetricObservation(
            assignment,
            (
                ("success_rate", baseline + 2.0 * assignment.repetition),
                ("utility", 1.0),
            ),
        )
        for assignment in assignments
    )

    aggregates = BasicStudyMetricAggregator().aggregate(
        protocol,
        observations,
        assignments,
    )
    control = next(
        item
        for item in aggregates
        if item.variant_id == "control" and item.metric_name == "success_rate"
    )

    assert control.mean == pytest.approx(baseline + 1.0)
    assert control.sample_variance == pytest.approx(2.0)
    assert control.standard_error == pytest.approx(1.0)


def test_study_aggregation_rejects_incomplete_matrix() -> None:
    protocol = _protocol()
    assignments = DeterministicStudyAssignment().assignments(protocol)
    observations = tuple(
        StudyMetricObservation(assignments[0], (("success_rate", 1.0), ("utility", 2.0)))
        for _ in (0,)
    )
    with pytest.raises(ValueError, match="matrix is incomplete"):
        BasicStudyMetricAggregator().aggregate(protocol, observations, assignments)


def test_study_aggregation_rejects_incomplete_metric_schema() -> None:
    protocol = _protocol()
    assignments = DeterministicStudyAssignment().assignments(protocol)
    observations = tuple(
        StudyMetricObservation(assignment, (("success_rate", 1.0),))
        for assignment in assignments
    )
    with pytest.raises(ValueError, match="metric schema is incomplete"):
        BasicStudyMetricAggregator().aggregate(protocol, observations, assignments)


def test_study_contracts_reject_bool_as_integer_identity() -> None:
    with pytest.raises(TypeError, match="repetitions must be an integer"):
        StudyProtocol(
            "study", "workload",
            (StudyVariantSpec("control", VariantKind.CONTROL, "fixed", "a" * 64),),
            True, "b" * 64, ("score",), "c" * 64,
            (AssignmentWorkload(("task-1",)),),
            ("standard",),
        )
    with pytest.raises(TypeError, match="repetition must be an integer"):
        StudyAssignment(
            "study",
            "control",
            True,
            "seed",
            AssignmentWorkload(("task-1",)),
        )


def test_study_contracts_reject_implicit_scalar_coercion() -> None:
    assignment = StudyAssignment(
        "study",
        "control",
        0,
        "seed",
        AssignmentWorkload(("task-1",)),
    )
    with pytest.raises(TypeError, match="must be numeric"):
        StudyMetricObservation(assignment, (("score", "1.0"),))
    with pytest.raises(TypeError, match="count must be an integer"):
        StudyMetricAggregate("study", "control", "score", True, 1.0, 0.0, 0.0)
    with pytest.raises(TypeError, match="kind must be VariantKind"):
        StudyVariantSpec("control", "control", "fixed", "a" * 64)


def test_study_aggregate_rejects_impossible_uncertainty_statistics() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        StudyMetricAggregate("study", "control", "score", 2, 1.0, -1.0, 0.0)


def test_study_digest_fields_require_canonical_sha256() -> None:
    with pytest.raises(ValueError):
        StudyVariantSpec("control", VariantKind.CONTROL, "fixed", "bogus")
    with pytest.raises(ValueError):
        StudyProtocol(
            "study", "workload",
            (StudyVariantSpec("control", VariantKind.CONTROL, "fixed", "a" * 64),),
            1, "bogus", (), "b" * 64,
            (AssignmentWorkload(("task-1",)),), ("standard",),
        )
    with pytest.raises(ValueError):
        StudyProtocol(
            "study", "workload",
            (StudyVariantSpec("control", VariantKind.CONTROL, "fixed", "a" * 64),),
            1, "b" * 64, (), "bogus",
            (AssignmentWorkload(("task-1",)),), ("standard",),
        )
