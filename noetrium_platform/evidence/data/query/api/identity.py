from __future__ import annotations

from noetrium_platform.evidence.data._canonical import canonical_digest
from .contracts import (
    ResearchDimension,
    ResearchResultQuery,
    ResearchResultRecord,
    ResearchSourceCut,
    ResearchSourceStatus,
)


def _dimension_document(row: ResearchDimension) -> dict[str, object]:
    return {"kind": row.kind.value, "value": row.value, "revision": row.revision}


def query_document(query: ResearchResultQuery) -> dict[str, object]:
    """Scientific selector identity; pins and page limits are read-consistency concerns."""

    return {
        "dimensions": tuple(_dimension_document(row) for row in query.dimensions),
        "kinds": tuple(row.value for row in query.kinds),
    }


def research_query_digest(query: ResearchResultQuery) -> str:
    return canonical_digest(query_document(query))


def record_document(row: ResearchResultRecord) -> dict[str, object]:
    return {
        "reference": {
            "kind": row.reference.kind.value,
            "result_id": row.reference.result_id,
            "source_authority": row.reference.source_authority,
        },
        "scope": {"kind": row.scope.kind.value, "scope_id": row.scope.scope_id},
        "content_sha256": row.content_sha256,
        "schema_ref": row.schema_ref,
        "dimensions": tuple(_dimension_document(item) for item in row.dimensions),
        "lineage": tuple(
            {
                "kind": item.kind.value,
                "result_id": item.result_id,
                "source_authority": item.source_authority,
            }
            for item in row.lineage
        ),
    }


def source_cut(
    source_id: str,
    query: ResearchResultQuery,
    records: tuple[ResearchResultRecord, ...],
) -> ResearchSourceCut:
    query_digest = research_query_digest(query)
    cut_digest = canonical_digest(
        {
            "source_id": source_id,
            "query_digest": query_digest,
            "records": tuple(record_document(row) for row in records),
        }
    )
    return ResearchSourceCut(
        source_id=source_id,
        query_digest=query_digest,
        cut_digest=cut_digest,
        record_count=len(records),
    )


def input_cut_digest(statuses: tuple[ResearchSourceStatus, ...]) -> str:
    return canonical_digest(
        tuple(
            {
                "source_id": row.source_id,
                "disposition": row.disposition.value,
                "diagnostic_code": row.diagnostic_code,
                "cut": None if row.cut is None else {
                    "query_digest": row.cut.query_digest,
                    "cut_digest": row.cut.cut_digest,
                    "record_count": row.cut.record_count,
                },
            }
            for row in statuses
        )
    )


__all__ = [
    "input_cut_digest",
    "query_document",
    "record_document",
    "research_query_digest",
    "source_cut",
]
