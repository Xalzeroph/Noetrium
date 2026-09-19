from __future__ import annotations

from dataclasses import asdict

from noetrium_platform.research.experimentation.run.api import RunArtifactKind, RunArtifactStorePort

from ..api import (
    StudyArtifactPublicationPort,
    StudyAssignment,
    StudyMetricAggregate,
    StudyMetricObservation,
    StudyProtocol,
)


class RunArtifactStudyPublication(StudyArtifactPublicationPort):
    """Publish study records through the run artifact authority."""

    def __init__(self, artifacts: RunArtifactStorePort) -> None:
        self._artifacts = artifacts

    def publish_protocol(
        self,
        protocol: StudyProtocol,
        assignments: tuple[StudyAssignment, ...],
    ) -> str:
        return self._artifacts.publish_json(
            "study/protocol.json",
            {
                "protocol": asdict(protocol),
                "assignments": [asdict(item) for item in assignments],
            },
            kind=RunArtifactKind.MANIFEST,
        )

    def publish_observations(
        self,
        observations: tuple[StudyMetricObservation, ...],
    ) -> str:
        return self._artifacts.publish_json(
            "study/observations.json",
            [asdict(item) for item in observations],
            kind=RunArtifactKind.METRIC,
        )

    def publish_aggregates(
        self,
        aggregates: tuple[StudyMetricAggregate, ...],
    ) -> str:
        return self._artifacts.publish_json(
            "study/aggregates.json",
            [asdict(item) for item in aggregates],
            kind=RunArtifactKind.METRIC,
        )


__all__ = ["RunArtifactStudyPublication"]
