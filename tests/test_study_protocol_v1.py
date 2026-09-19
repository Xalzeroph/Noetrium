from __future__ import annotations

from noetrium_platform.research.experimentation.study.api import (
    StudyConcurrencyPolicy,
    StudyAssignment,
    StudyMetricAggregate,
    StudyMetricObservation,
    StudyProtocol,
    StudyVariantSpec,
    VariantKind,
)
from noetrium_platform.research.experimentation.study.runtime import BasicStudyMetricAggregator, DeterministicStudyAssignment
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
        ("standard",),
        StudyConcurrencyPolicy.serial_shared_v1(repetition_timeout_seconds=3600.0),
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
            ("standard",),
            StudyConcurrencyPolicy.serial_shared_v1(repetition_timeout_seconds=3600.0),
        )
    with pytest.raises(TypeError, match="repetition must be an integer"):
        StudyAssignment("study", "control", True, "seed")
    with pytest.raises(TypeError, match="max_parallel_repetitions must be an integer"):
        StudyConcurrencyPolicy(
            True, False, "shared", "shared", "shared",
            "runtime-hierarchical-v1", "deterministic-priority-fair-v1",
            3600.0, 1,
        )


def test_study_contracts_reject_implicit_scalar_coercion() -> None:
    assignment = StudyAssignment("study", "control", 0, "seed")
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
            1, "bogus", (), "b" * 64, ("standard",),
            StudyConcurrencyPolicy.serial_shared_v1(repetition_timeout_seconds=3600.0),
        )
    with pytest.raises(ValueError):
        StudyProtocol(
            "study", "workload",
            (StudyVariantSpec("control", VariantKind.CONTROL, "fixed", "a" * 64),),
            1, "b" * 64, (), "bogus", ("standard",),
            StudyConcurrencyPolicy.serial_shared_v1(repetition_timeout_seconds=3600.0),
        )
