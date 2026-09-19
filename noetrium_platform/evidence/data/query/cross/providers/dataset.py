from __future__ import annotations

from noetrium_platform.evidence.data.dataset.api import DatasetQuery, DatasetRegistryPort, DatasetVersion
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

from ._common import matches_query, scope_dimensions


class DatasetResearchResultSource:
    source_id = "data.dataset"
    supported_kinds = frozenset({ResearchResultKind.DATASET})
    supported_dimensions = frozenset(
        {
            ResearchDimensionKind.PROJECT,
            ResearchDimensionKind.STUDY,
            ResearchDimensionKind.RUN,
            ResearchDimensionKind.DATASET,
        }
    )
    _SOURCE_LIMIT = 10_000

    def __init__(self, registry: DatasetRegistryPort, scopes: ScopeRegistryPort) -> None:
        self._registry = registry
        self._scopes = scopes

    def _record(self, dataset: DatasetVersion) -> ResearchResultRecord:
        dimensions = scope_dimensions(dataset.scope, self._scopes) + (
            ResearchDimension(
                ResearchDimensionKind.DATASET,
                dataset.identity.dataset_id,
                dataset.identity.version,
            ),
        )
        lineage = tuple(
            ResearchResultReference(
                ResearchResultKind.DATASET,
                parent.key,
                self.source_id,
            )
            for parent in dataset.parent_versions
        )
        return ResearchResultRecord(
            reference=ResearchResultReference(
                ResearchResultKind.DATASET,
                dataset.identity.key,
                self.source_id,
            ),
            scope=dataset.scope,
            content_sha256=dataset.content_sha256,
            schema_ref=dataset.schema_ref,
            dimensions=tuple(sorted(dimensions, key=lambda row: row.kind.value)),
            lineage=lineage,
        )
    def snapshot(self, query: ResearchResultQuery) -> ResearchSourceSnapshot:
        rows = self._registry.query(DatasetQuery(limit=self._SOURCE_LIMIT))
        if len(rows) == self._SOURCE_LIMIT:
            raise ResearchQuerySourceError(
                self.source_id,
                "SOURCE_LIMIT_REACHED",
                "dataset registry cannot prove the query cut is complete at its hard source limit",
                disposition=ResearchSourceDisposition.INCOMPLETE,
            )
        records = tuple(
            sorted(
                (record for record in map(self._record, rows) if matches_query(record, query)),
                key=lambda row: row.reference.result_id,
            )
        )
        return ResearchSourceSnapshot(
            source_id=self.source_id,
            cut=source_cut(self.source_id, query, records),
            records=records,
        )


__all__ = ["DatasetResearchResultSource"]
