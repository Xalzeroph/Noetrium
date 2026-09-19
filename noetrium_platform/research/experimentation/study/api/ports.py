from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import (
    StudyAssignment,
    StudyExecutionUnit,
    StudyMetricAggregate,
    StudyMetricObservation,
    StudyProtocol,
)
from .plan import VariantBinding


class StudyAssignmentPort(Protocol):
    """Deterministic authoring/compiler service for expanding a StudyProtocol."""

    def assignments(self, protocol: StudyProtocol) -> tuple[StudyAssignment, ...]: ...


class StudyMetricAggregationPort(Protocol):
    def aggregate(
        self,
        protocol: StudyProtocol,
        observations: tuple[StudyMetricObservation, ...],
        expected_assignments: tuple[StudyAssignment, ...],
    ) -> tuple[StudyMetricAggregate, ...]: ...


@runtime_checkable
class BoundStudyExecutionPort(Protocol):
    """Complete provider seam for execution of one frozen ExperimentPlan.

    The provider receives only assignments plus their frozen VariantBindings.
    Both grouped and independent-variant entrypoints are mandatory so scientific
    concurrency policy never changes the provider contract at runtime.
    """

    def execute_bound(
        self,
        unit: StudyExecutionUnit,
        bindings: tuple[VariantBinding, ...],
        plan_digest: str,
    ) -> tuple[StudyMetricObservation, ...]: ...

    def execute_bound_variant(
        self,
        assignment: StudyAssignment,
        binding: VariantBinding,
        plan_digest: str,
    ) -> StudyMetricObservation: ...


class StudyArtifactPublicationPort(Protocol):
    """Durable publication seam for frozen protocol and derived statistics."""

    def publish_protocol(
        self,
        protocol: StudyProtocol,
        assignments: tuple[StudyAssignment, ...],
    ) -> str: ...

    def publish_observations(
        self,
        observations: tuple[StudyMetricObservation, ...],
    ) -> str: ...

    def publish_aggregates(
        self,
        aggregates: tuple[StudyMetricAggregate, ...],
    ) -> str: ...


__all__ = [
    "BoundStudyExecutionPort",
    "StudyArtifactPublicationPort",
    "StudyAssignmentPort",
    "StudyMetricAggregationPort",
]
