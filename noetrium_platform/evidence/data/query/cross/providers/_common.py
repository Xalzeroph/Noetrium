from __future__ import annotations

from noetrium_platform.evidence.data.query.api import (
    ResearchDimension,
    ResearchDimensionKind,
    ResearchResultQuery,
    ResearchResultRecord,
)
from noetrium_platform.foundation.api import (
    NoetriumUnit,
    ScopeIndexPort,
    ScopeKind,
    scope_id,
    scope_kind,
)


_SCOPE_DIMENSIONS = {
    ScopeKind.PROJECT: ResearchDimensionKind.PROJECT,
    ScopeKind.STUDY: ResearchDimensionKind.STUDY,
    ScopeKind.RUN: ResearchDimensionKind.RUN,
}


def scope_dimensions(
    scope: NoetriumUnit,
    registry: ScopeIndexPort,
) -> tuple[ResearchDimension, ...]:
    rows = []
    for item in registry.ancestry(scope):
        kind = _SCOPE_DIMENSIONS.get(scope_kind(item))
        if kind is not None:
            rows.append(ResearchDimension(kind, scope_id(item)))
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
