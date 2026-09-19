from __future__ import annotations

from noetrium_platform.evidence.data.query.api import (
    ResearchDimension,
    ResearchDimensionKind,
    ResearchResultQuery,
    ResearchResultRecord,
)
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind, ScopeRegistryPort


_SCOPE_DIMENSIONS = {
    ScopeKind.PROJECT: ResearchDimensionKind.PROJECT,
    ScopeKind.STUDY: ResearchDimensionKind.STUDY,
    ScopeKind.RUN: ResearchDimensionKind.RUN,
}


def scope_dimensions(
    scope: ScopeIdentity,
    registry: ScopeRegistryPort,
) -> tuple[ResearchDimension, ...]:
    rows = []
    for item in registry.ancestry(scope):
        kind = _SCOPE_DIMENSIONS.get(item.kind)
        if kind is not None:
            rows.append(ResearchDimension(kind, item.scope_id))
    rows.sort(key=lambda row: row.kind.value)
    return tuple(rows)


def matches_query(record: ResearchResultRecord, query: ResearchResultQuery) -> bool:
    if query.kinds and record.reference.kind not in query.kinds:
        return False
    available = {row.kind: row for row in record.dimensions}
    for required in query.dimensions:
        if available.get(required.kind) != required:
            return False
    return True


__all__ = ["matches_query", "scope_dimensions"]
