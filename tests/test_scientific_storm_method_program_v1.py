from __future__ import annotations

from hashlib import sha256

from research.benchmarks.freshwiki import (
    FRESHWIKI_BENCHMARK_ID,
    FreshWikiTopicRecord,
    build_freshwiki_task_set,
)
from research.reproductions.storm_wiki import (
    STORM_WIKI_REFERENCE_FIDELITY,
    build_storm_freshwiki_study,
    build_storm_wiki_method_program,
)


def _benchmark():
    record = FreshWikiTopicRecord(
        "freshwiki:test:001",
        "Agent research systems",
        sha256(b"reference-article").hexdigest(),
    )
    return build_freshwiki_task_set(
        (record,),
        dataset_content_sha256=sha256(b"freshwiki-test-cut").hexdigest(),
        require_paper_cardinality=False,
    )


def test_storm_method_program_freezes_search_capability_and_pipeline_bounds() -> None:
    first = build_storm_wiki_method_program(
        search_capability_id="retrieval.search.paper-era",
    )
    second = build_storm_wiki_method_program(
        search_capability_id="retrieval.search.other-cut",
    )
    assert first.program_digest != second.program_digest
    assert first.required_capabilities == ("retrieval.search.paper-era",)
    assert "heading_soft_recall" in first.metric_names
    assert (
        STORM_WIKI_REFERENCE_FIDELITY.max_perspectives
        * STORM_WIKI_REFERENCE_FIDELITY.max_conversation_turns
        == 9
    )


def test_storm_freshwiki_study_binds_paper_metrics() -> None:
    benchmark = _benchmark()
    assert benchmark.benchmark_id == FRESHWIKI_BENCHMARK_ID
    study = build_storm_freshwiki_study(
        benchmark,
        split_id="paper-eval",
        search_capability_id="retrieval.search.paper-era",
    )
    assert study.benchmark.cut_digest == benchmark.cut_digest
    assert study.trial_protocol_identity.protocol_id == (
        "storm.naacl2024.freshwiki.v1"
    )
    assert tuple(
        row.measurement_id for row in study.measurement_protocol.measurements
    ) == (
        "heading_soft_recall",
        "heading_entity_recall",
        "rouge",
        "entity_recall",
        "rubric_score",
        "model_call_count",
        "search_call_count",
    )
