from __future__ import annotations

from resource_test_support import build_test_platform_meta

from noetrium_platform.composition.platform_meta import build_platform_meta
from noetrium_platform.evidence.data.query.api import ResearchResultQuery


def test_platform_meta_owns_cross_query_authority(tmp_path) -> None:
    meta = build_test_platform_meta(tmp_path / "meta")
    page = meta.research_results.query(ResearchResultQuery())
    assert page.records == ()
    assert {row.source_id for row in page.sources} == {
        "artifact.catalog",
        "data.dataset",
    }


def test_platform_meta_cross_query_authority_survives_rebuild(tmp_path) -> None:
    first = build_test_platform_meta(tmp_path)
    assert first.research_results.query().records == ()
    second = build_test_platform_meta(tmp_path)
    assert second.research_results.query().records == ()
