from __future__ import annotations

import math
from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .api import (
    StudyAssignment,
    StudyAssignmentPort,
    StudyMetricAggregate,
    StudyMetricAggregationPort,
    StudyMetricObservation,
    StudyProtocol,
)


def _assignment_for_variant(
    protocol: StudyProtocol,
    repetition: int,
    variant_id: str,
) -> StudyAssignment:
    return StudyAssignment(
        protocol.study_id,
        variant_id,
        repetition,
        canonical_digest(
            {
                "study_id": protocol.study_id,
                "workload_id": protocol.workload_id,
                "variant_id": variant_id,
                "repetition": repetition,
                "seed_schedule_digest": protocol.seed_schedule_digest,
            }
        ),
    )


def _assignments_for_repetition(
    protocol: StudyProtocol,
    repetition: int,
) -> tuple[StudyAssignment, ...]:
    return tuple(
        _assignment_for_variant(protocol, repetition, variant.variant_id)
        for variant in protocol.variants
    )


class DeterministicStudyAssignment(StudyAssignmentPort):
    """Expand every declared variant and repetition without hidden sampling."""

    def assignments(self, protocol: StudyProtocol) -> tuple[StudyAssignment, ...]:
        assignments: list[StudyAssignment] = []
        for repetition in range(protocol.repetitions):
            assignments.extend(_assignments_for_repetition(protocol, repetition))
        return tuple(assignments)


def _require_observation_schema(
    observation: StudyMetricObservation,
    expected_names: set[str],
) -> str:
    digest = observation.assignment.assignment_digest
    actual_names = {name for name, _ in observation.metrics}
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise ValueError(
            "study observation metric schema is incomplete: "
            f"missing={missing!r} extra={extra!r}"
        )
    return digest


def _index_observations(
    protocol: StudyProtocol,
    expected_by_digest: dict[str, StudyAssignment],
    observations: tuple[StudyMetricObservation, ...],
) -> dict[str, StudyMetricObservation]:
    observed: dict[str, StudyMetricObservation] = {}
    expected_names = set(protocol.metric_names)
    for observation in observations:
        digest = _require_observation_schema(observation, expected_names)
        if digest in observed:
            raise ValueError(f"study contains duplicate assignment observation: {digest}")
        if digest not in expected_by_digest:
            raise ValueError("study observation references an undeclared assignment")
        observed[digest] = observation
    return observed


def _require_complete_matrix(
    expected_by_digest: dict[str, StudyAssignment],
    observed_by_digest: dict[str, StudyMetricObservation],
) -> None:
    missing_assignments = set(expected_by_digest) - set(observed_by_digest)
    if missing_assignments:
        raise ValueError(
            "study matrix is incomplete; missing assignment observations: "
            + ", ".join(sorted(missing_assignments))
        )


@dataclass(slots=True)
class _OnlineMetricStats:
    """Numerically stable single-pass sample statistics."""

    count: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def add(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)

    @property
    def variance(self) -> float:
        return self.m2 / (self.count - 1) if self.count > 1 else 0.0


def _group_metric_stats(
    protocol: StudyProtocol,
    observations: tuple[StudyMetricObservation, ...],
) -> dict[tuple[str, str], _OnlineMetricStats]:
    grouped: dict[tuple[str, str], _OnlineMetricStats] = {}
    allowed = set(protocol.metric_names)
    for observation in observations:
        if observation.assignment.study_id != protocol.study_id:
            raise ValueError("study observation belongs to another study")
        for name, value in observation.metrics:
            if name not in allowed:
                raise ValueError(
                    f"study observation contains undeclared metric: {name}"
                )
            grouped.setdefault(
                (observation.assignment.variant_id, name),
                _OnlineMetricStats(),
            ).add(float(value))
    return grouped


def _aggregate_group(
    protocol: StudyProtocol,
    variant_id: str,
    metric_name: str,
    stats: _OnlineMetricStats,
) -> StudyMetricAggregate:
    variance = stats.variance
    return StudyMetricAggregate(
        protocol.study_id,
        variant_id,
        metric_name,
        stats.count,
        stats.mean,
        variance,
        math.sqrt(variance / stats.count),
    )


class BasicStudyMetricAggregator(StudyMetricAggregationPort):
    """Pure mean/variance aggregation; no significance claim is implied."""

    def aggregate(
        self,
        protocol: StudyProtocol,
        observations: tuple[StudyMetricObservation, ...],
        expected_assignments: tuple[StudyAssignment, ...],
    ) -> tuple[StudyMetricAggregate, ...]:
        expected = expected_assignments
        expected_by_digest = {item.assignment_digest: item for item in expected}
        observed_by_digest = _index_observations(
            protocol, expected_by_digest, observations
        )
        _require_complete_matrix(expected_by_digest, observed_by_digest)
        grouped = _group_metric_stats(protocol, observations)
        return tuple(
            _aggregate_group(protocol, variant_id, metric_name, stats)
            for (variant_id, metric_name), stats in sorted(grouped.items())
        )


__all__ = ["BasicStudyMetricAggregator", "DeterministicStudyAssignment"]
