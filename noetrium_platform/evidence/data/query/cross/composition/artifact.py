from __future__ import annotations

from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactQuery,
    ArtifactRecord,
    ArtifactRegistryPort,
)
from noetrium_platform.evidence.data.query.api import (
    ResearchDimension,
    ResearchDimensionKind,
    ResearchQuerySourceError,
    ResearchResultKind,
    ResearchResultQuery,
    ResearchResultRecord,
    ResearchResultReference,
    ResearchSourceDisposition,
    ResearchSourceSnapshot,
)
from noetrium_platform.evidence.data.query.api.identity import source_cut
from noetrium_platform.foundation.scope.api import ScopeRegistryPort

from noetrium_platform.evidence.data.query.cross.providers._common import matches_query, scope_dimensions


_KIND_MAP = {
    ArtifactKind.DATASET: ResearchResultKind.DATASET,
    ArtifactKind.REPORT: ResearchResultKind.REPORT,
    ArtifactKind.PUBLICATION: ResearchResultKind.PUBLICATION,
}


class ArtifactCatalogResearchResultSource:
    source_id = "artifact.catalog"
    supported_kinds = frozenset(
        {
            ResearchResultKind.ARTIFACT,
            ResearchResultKind.DATASET,
            ResearchResultKind.REPORT,
            ResearchResultKind.PUBLICATION,
        }
    )
    supported_dimensions = frozenset(
        {
            ResearchDimensionKind.PROJECT,
            ResearchDimensionKind.STUDY,
            ResearchDimensionKind.RUN,
            ResearchDimensionKind.COMPONENT,
            ResearchDimensionKind.REPORT,
            ResearchDimensionKind.PUBLICATION,
        }
    )
    _SOURCE_LIMIT = 10_000

    def __init__(self, registry: ArtifactRegistryPort, scopes: ScopeRegistryPort) -> None:
        self._registry = registry
        self._scopes = scopes

    @staticmethod
    def _result_kind(record: ArtifactRecord) -> ResearchResultKind:
        return _KIND_MAP.get(record.kind, ResearchResultKind.ARTIFACT)

    def _record(self, artifact: ArtifactRecord) -> ResearchResultRecord:
        result_kind = self._result_kind(artifact)
        dimensions = list(scope_dimensions(artifact.scope, self._scopes))
        dimensions.append(ResearchDimension(ResearchDimensionKind.COMPONENT, artifact.producer_component_id))
        if result_kind is ResearchResultKind.REPORT:
            dimensions.append(ResearchDimension(ResearchDimensionKind.REPORT, artifact.artifact_id))
        elif result_kind is ResearchResultKind.PUBLICATION:
            dimensions.append(ResearchDimension(ResearchDimensionKind.PUBLICATION, artifact.artifact_id))
        lineage = tuple(
            ResearchResultReference(ResearchResultKind.ARTIFACT, ref.artifact_id, self.source_id)
            for ref in artifact.lineage
        )
        return ResearchResultRecord(
            reference=ResearchResultReference(result_kind, artifact.artifact_id, self.source_id),
            scope=artifact.scope,
            content_sha256=artifact.digest,
            dimensions=tuple(sorted(dimensions, key=lambda row: row.kind.value)),
            lineage=lineage,
        )

    def snapshot(self, query: ResearchResultQuery) -> ResearchSourceSnapshot:
        rows = self._registry.query(ArtifactQuery(limit=self._SOURCE_LIMIT))
        if len(rows) == self._SOURCE_LIMIT:
            raise ResearchQuerySourceError(
                self.source_id,
                "SOURCE_LIMIT_REACHED",
                "artifact catalog cannot prove the query cut is complete at its hard source limit",
                disposition=ResearchSourceDisposition.INCOMPLETE,
            )
        records = tuple(
            sorted(
                (record for record in map(self._record, rows) if matches_query(record, query)),
                key=lambda row: (row.reference.kind.value, row.reference.result_id),
            )
        )
        return ResearchSourceSnapshot(
            source_id=self.source_id,
            cut=source_cut(self.source_id, query, records),
            records=records,
        )


__all__ = ["ArtifactCatalogResearchResultSource"]
