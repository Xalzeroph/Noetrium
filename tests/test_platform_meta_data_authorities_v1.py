from __future__ import annotations

from noetrium_platform.composition.platform_meta import (
    build_durable_platform_meta,
    build_in_memory_platform_meta,
)
from noetrium_platform.evidence.data.fact.api import (
    DurableFact,
    FactCriticality,
)
from noetrium_platform.evidence.data.query.api import ResearchResultQuery


def _fact() -> DurableFact:
    return DurableFact(
        fact_id="fact:test:1",
        fact_type="test.fact",
        schema_version="v1",
        criticality=FactCriticality.REQUIRED,
        payload={"value": 7},
        artifact_refs=("artifact:test",),
        state_refs=("state:test",),
    )


def test_in_memory_platform_meta_owns_fact_and_cross_query_authorities() -> None:
    meta = build_in_memory_platform_meta()
    fact = _fact()
    receipt = meta.facts.append(fact)

    assert receipt.fact_id == fact.fact_id
    assert meta.facts.get(fact.fact_id) == fact
    assert meta.facts.count() == 1

    page = meta.research_results.query(ResearchResultQuery())
    assert page.records == ()
    assert {row.source_id for row in page.sources} == {
        "artifact.catalog",
        "data.dataset",
    }


def test_durable_platform_meta_fact_authority_survives_rebuild(tmp_path) -> None:
    first = build_durable_platform_meta(tmp_path)
    fact = _fact()
    first.facts.append(fact)

    second = build_durable_platform_meta(tmp_path)
    assert second.facts.get(fact.fact_id) == fact
    assert second.facts.count() == 1
    assert second.research_results.query().records == ()
