from __future__ import annotations

from noetrium_platform.evidence.data.query.api import (
    ResearchQueryGap,
    ResearchQueryGapKind,
    ResearchQuerySourceError,
    ResearchResultPage,
    ResearchResultQuery,
    ResearchResultSourcePort,
    ResearchSourceDisposition,
    ResearchSourceStatus,
)
from noetrium_platform.evidence.data.query.api.identity import input_cut_digest, research_query_digest


class CrossAuthorityResearchResultQuery:
    """Read-only federation over producer-owned immutable result projections."""

    def __init__(self, sources: tuple[ResearchResultSourcePort, ...]) -> None:
        if not sources:
            raise ValueError("research result federation requires at least one source")
        source_ids = [row.source_id for row in sources]
        if any(not source_id.strip() for source_id in source_ids):
            raise ValueError("research result source ids must be non-empty")
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("research result source ids must be unique")
        self._sources = tuple(sorted(sources, key=lambda row: row.source_id))

    def _capability_gaps(self, query: ResearchResultQuery) -> tuple[ResearchQueryGap, ...]:
        supported_kinds = frozenset(kind for source in self._sources for kind in source.supported_kinds)
        supported_dimensions = frozenset(
            kind for source in self._sources for kind in source.supported_dimensions
        )
        gaps = [
            ResearchQueryGap(
                ResearchQueryGapKind.RESULT_KIND,
                kind.value,
                "NO_SOURCE_CAPABILITY",
            )
            for kind in query.kinds
            if kind not in supported_kinds
        ]
        gaps.extend(
            ResearchQueryGap(
                ResearchQueryGapKind.DIMENSION,
                dimension.kind.value,
                "NO_SOURCE_CAPABILITY",
            )
            for dimension in query.dimensions
            if dimension.kind not in supported_dimensions
        )
        configured = {source.source_id for source in self._sources}
        gaps.extend(
            ResearchQueryGap(
                ResearchQueryGapKind.PINNED_SOURCE,
                cut.source_id,
                "PINNED_SOURCE_NOT_CONFIGURED",
            )
            for cut in query.pinned_source_cuts
            if cut.source_id not in configured
        )
        return tuple(sorted(gaps))

    def query(self, query: ResearchResultQuery = ResearchResultQuery()) -> ResearchResultPage:
        query_digest = research_query_digest(query)
        expected_cuts = {row.source_id: row for row in query.pinned_source_cuts}
        statuses: list[ResearchSourceStatus] = []
        records = []
        for source in self._sources:
            try:
                snapshot = source.snapshot(query)
            except ResearchQuerySourceError as exc:
                if exc.source_id != source.source_id:
                    raise RuntimeError("research query source error misreported source identity") from exc
                statuses.append(
                    ResearchSourceStatus(
                        source_id=source.source_id,
                        disposition=exc.disposition,
                        diagnostic_code=exc.code,
                    )
                )
                continue
            if snapshot.source_id != source.source_id:
                raise RuntimeError("research query source returned another source identity")
            if snapshot.cut.query_digest != query_digest:
                raise RuntimeError("research query source cut does not bind the requested selector")
            expected = expected_cuts.get(source.source_id)
            if expected is not None and expected.query_digest != query_digest:
                statuses.append(
                    ResearchSourceStatus(
                        source_id=source.source_id,
                        disposition=ResearchSourceDisposition.STALE,
                        cut=snapshot.cut,
                        diagnostic_code="PIN_QUERY_MISMATCH",
                    )
                )
                continue
            if expected is not None and (
                expected.cut_digest != snapshot.cut.cut_digest
                or expected.record_count != snapshot.cut.record_count
            ):
                statuses.append(
                    ResearchSourceStatus(
                        source_id=source.source_id,
                        disposition=ResearchSourceDisposition.STALE,
                        cut=snapshot.cut,
                        diagnostic_code="PINNED_CUT_MISMATCH",
                    )
                )
                continue
            statuses.append(
                ResearchSourceStatus(
                    source_id=source.source_id,
                    disposition=ResearchSourceDisposition.COMPLETE,
                    cut=snapshot.cut,
                )
            )
            records.extend(snapshot.records)

        gaps = self._capability_gaps(query)
        all_records = tuple(
            sorted(
                records,
                key=lambda row: (
                    row.reference.source_authority,
                    row.reference.kind.value,
                    row.reference.result_id,
                ),
            )
        )
        ordered_records = all_records[: query.limit]
        truncated = len(all_records) > len(ordered_records)
        complete = not gaps and not truncated and all(
            row.disposition is ResearchSourceDisposition.COMPLETE for row in statuses
        )
        return ResearchResultPage(
            query_digest=query_digest,
            input_cut_digest=input_cut_digest(
                tuple(sorted(statuses, key=lambda row: row.source_id))
            ),
            records=ordered_records,
            sources=tuple(statuses),
            matched_count=len(all_records),
            truncated=truncated,
            gaps=gaps,
            complete=complete,
        )


__all__ = ["CrossAuthorityResearchResultQuery"]
