from __future__ import annotations

import hashlib

import pytest

from noetrium_platform.evidence.data.query.api import (
    ResearchDimension,
    ResearchDimensionKind,
    ResearchQueryGapKind,
    ResearchQuerySourceError,
    ResearchResultKind,
    ResearchResultQuery,
    ResearchResultRecord,
    ResearchResultReference,
    ResearchSourceDisposition,
    ResearchSourceSnapshot,
)
from noetrium_platform.evidence.data.query.api.identity import source_cut
from noetrium_platform.evidence.data.query.cross.composition import compose
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE


def _record(source_id: str, result_id: str) -> ResearchResultRecord:
    return ResearchResultRecord(
        reference=ResearchResultReference(
            ResearchResultKind.DATASET,
            result_id,
            source_id,
        ),
        scope=PLATFORM_SCOPE,
        content_sha256=hashlib.sha256(result_id.encode("utf-8")).hexdigest(),
    )


class _StaticSource:
    supported_kinds = frozenset({ResearchResultKind.DATASET})
    supported_dimensions = frozenset()

    def __init__(self, source_id: str, records: tuple[ResearchResultRecord, ...]) -> None:
        self.source_id = source_id
        self._records = records

    def snapshot(self, query: ResearchResultQuery) -> ResearchSourceSnapshot:
        return ResearchSourceSnapshot(
            source_id=self.source_id,
            cut=source_cut(self.source_id, query, self._records),
            records=self._records,
        )


def test_source_and_record_ordering_is_deterministic_across_composition_order() -> None:
    source_a = _StaticSource("source.a", (_record("source.a", "shared"),))
    source_b = _StaticSource("source.b", (_record("source.b", "shared"),))
    query = ResearchResultQuery(kinds=(ResearchResultKind.DATASET,))

    reverse = compose((source_b, source_a)).query(query)
    forward = compose((source_a, source_b)).query(query)

    assert [row.source_id for row in reverse.sources] == ["source.a", "source.b"]
    assert [row.reference.source_authority for row in reverse.records] == ["source.a", "source.b"]
    assert reverse.records == forward.records
    assert reverse.input_cut_digest == forward.input_cut_digest
    assert reverse.query_digest == forward.query_digest
    assert reverse.complete is forward.complete is True


def test_snapshot_rejects_duplicate_and_foreign_authority_records() -> None:
    query = ResearchResultQuery(kinds=(ResearchResultKind.DATASET,))
    record = _record("source.a", "duplicate")
    duplicate_records = (record, record)
    with pytest.raises(ValueError, match="duplicate result references"):
        ResearchSourceSnapshot(
            source_id="source.a",
            cut=source_cut("source.a", query, duplicate_records),
            records=duplicate_records,
        )

    foreign = _record("source.b", "foreign")
    with pytest.raises(ValueError, match="foreign source-authority"):
        ResearchSourceSnapshot(
            source_id="source.a",
            cut=source_cut("source.a", query, (foreign,)),
            records=(foreign,),
        )


def test_unavailable_source_and_unsupported_dimension_are_explicit() -> None:
    class UnavailableSource:
        source_id = "source.unavailable"
        supported_kinds = frozenset({ResearchResultKind.DATASET})
        supported_dimensions = frozenset()

        def snapshot(self, query):
            del query
            raise ResearchQuerySourceError(self.source_id, "OFFLINE", "source is offline")

    page = compose((UnavailableSource(),)).query(
        ResearchResultQuery(
            kinds=(ResearchResultKind.DATASET,),
            dimensions=(ResearchDimension(ResearchDimensionKind.ENVIRONMENT, "env-a"),),
        )
    )

    assert page.complete is False
    assert page.records == ()
    assert page.sources[0].disposition is ResearchSourceDisposition.UNAVAILABLE
    assert page.sources[0].diagnostic_code == "OFFLINE"
    assert page.gaps == (
        next(
            gap
            for gap in page.gaps
            if gap.kind is ResearchQueryGapKind.DIMENSION
        ),
    )
    assert page.gaps[0].value == ResearchDimensionKind.ENVIRONMENT.value
    assert page.gaps[0].diagnostic_code == "NO_SOURCE_CAPABILITY"


def test_limit_truncation_is_incomplete_but_preserves_underlying_cut_identity() -> None:
    source = _StaticSource(
        "source.a",
        (_record("source.a", "a"), _record("source.a", "b")),
    )
    limited = compose((source,)).query(
        ResearchResultQuery(kinds=(ResearchResultKind.DATASET,), limit=1)
    )
    full = compose((source,)).query(
        ResearchResultQuery(kinds=(ResearchResultKind.DATASET,), limit=2)
    )

    assert limited.matched_count == 2
    assert limited.truncated is True
    assert limited.complete is False
    assert len(limited.records) == 1
    assert full.matched_count == 2
    assert full.truncated is False
    assert full.complete is True
    assert limited.query_digest == full.query_digest
    assert limited.input_cut_digest == full.input_cut_digest


def test_query_contracts_reject_untyped_impostors_at_construction() -> None:
    with pytest.raises(TypeError, match="kinds must contain ResearchResultKind"):
        ResearchResultQuery(kinds=("dataset",))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="kind must be ResearchDimensionKind"):
        ResearchDimension("project", "paper-a")  # type: ignore[arg-type]

    query = ResearchResultQuery(kinds=(ResearchResultKind.DATASET,))
    cut = source_cut("source.a", query, (_record("source.a", "one"),))
    from noetrium_platform.evidence.data.query.api import ResearchSourceStatus

    with pytest.raises(ValueError, match="cut source_id must match"):
        ResearchSourceStatus(
            source_id="source.b",
            disposition=ResearchSourceDisposition.STALE,
            cut=cut,
            diagnostic_code="STALE",
        )


def test_run_task_action_observation_kinds_are_explicit_and_fail_closed_without_source() -> None:
    class EmptyDatasetSource:
        source_id = "source.dataset"
        supported_kinds = frozenset({ResearchResultKind.DATASET})
        supported_dimensions = frozenset()

        def snapshot(self, query):
            records = ()
            return ResearchSourceSnapshot(
                self.source_id,
                source_cut(self.source_id, query, records),
                records,
            )

    federation = compose((EmptyDatasetSource(),))
    for kind in (
        ResearchResultKind.RUN,
        ResearchResultKind.TASK,
        ResearchResultKind.ACTION,
        ResearchResultKind.OBSERVATION,
    ):
        page = federation.query(ResearchResultQuery(kinds=(kind,)))
        assert page.complete is False
        assert page.records == ()
        assert len(page.gaps) == 1
        assert page.gaps[0].kind is ResearchQueryGapKind.RESULT_KIND
        assert page.gaps[0].value == kind.value
        assert page.gaps[0].diagnostic_code == "NO_SOURCE_CAPABILITY"
