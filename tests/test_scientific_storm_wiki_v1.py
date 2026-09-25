from __future__ import annotations

import hashlib

import pytest

from research.reproductions.storm_wiki import (
    STORM_WIKI_AUDITED_COMMIT,
    STORM_WIKI_REFERENCE_FIDELITY,
    STORM_WIKI_STAGE_OUTPUTS,
    StormWikiPipelineState,
    StormWikiStage,
    StormWikiStageReceipt,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_storm_paper_era_research_pipeline_is_pinned() -> None:
    fidelity = STORM_WIKI_REFERENCE_FIDELITY
    assert STORM_WIKI_AUDITED_COMMIT == "1f8ac2ddb4dd5f8cfcc250fdd3611c693098134b"
    assert fidelity.stage_order == (
        "knowledge_curation",
        "outline_generation",
        "article_generation",
        "article_polishing",
    )
    assert fidelity.max_perspectives == 3
    assert fidelity.max_conversation_turns == 3
    assert fidelity.max_search_queries_per_turn == 3
    assert fidelity.search_top_k == 3
    assert fidelity.section_retrieve_top_k == 3
    assert fidelity.per_result_snippet_count == 1
    assert fidelity.expert_information_word_limit == 1000
    assert fidelity.recent_full_dialogue_turns_in_question_context == 4


def test_storm_stage_outputs_match_resume_files_from_paper_era_runner() -> None:
    assert STORM_WIKI_STAGE_OUTPUTS[StormWikiStage.KNOWLEDGE_CURATION] == (
        "conversation_log.json",
        "raw_search_results.json",
    )
    assert STORM_WIKI_STAGE_OUTPUTS[StormWikiStage.OUTLINE_GENERATION] == (
        "storm_gen_outline.txt",
        "direct_gen_outline.txt",
    )
    assert STORM_WIKI_STAGE_OUTPUTS[StormWikiStage.ARTICLE_GENERATION] == (
        "storm_gen_article.txt",
        "url_to_info.json",
    )
    assert STORM_WIKI_STAGE_OUTPUTS[StormWikiStage.ARTICLE_POLISHING] == (
        "storm_gen_article_polished.txt",
    )


def test_storm_pipeline_state_binds_each_stage_to_exact_upstream_artifact_digests() -> None:
    state = StormWikiPipelineState("agent research")
    knowledge = StormWikiStageReceipt(
        StormWikiStage.KNOWLEDGE_CURATION,
        _digest("knowledge"),
    )
    state = state.append(knowledge)
    outline = StormWikiStageReceipt(
        StormWikiStage.OUTLINE_GENERATION,
        _digest("outline"),
        (knowledge.output_bundle_digest,),
    )
    state = state.append(outline)
    article = StormWikiStageReceipt(
        StormWikiStage.ARTICLE_GENERATION,
        _digest("article"),
        (knowledge.output_bundle_digest, outline.output_bundle_digest),
    )
    state = state.append(article)
    polished = StormWikiStageReceipt(
        StormWikiStage.ARTICLE_POLISHING,
        _digest("polished"),
        (article.output_bundle_digest,),
    )
    state = state.append(polished)

    assert state.next_stage is None
    assert tuple(receipt.stage for receipt in state.receipts) == (
        StormWikiStage.KNOWLEDGE_CURATION,
        StormWikiStage.OUTLINE_GENERATION,
        StormWikiStage.ARTICLE_GENERATION,
        StormWikiStage.ARTICLE_POLISHING,
    )


def test_storm_pipeline_fails_closed_on_skipped_or_rebound_dependencies() -> None:
    state = StormWikiPipelineState("agent research")
    with pytest.raises(ValueError, match="before its dependencies"):
        state.append(
            StormWikiStageReceipt(
                StormWikiStage.OUTLINE_GENERATION,
                _digest("outline"),
                (_digest("missing-knowledge"),),
            )
        )

    knowledge = StormWikiStageReceipt(
        StormWikiStage.KNOWLEDGE_CURATION,
        _digest("knowledge"),
    )
    state = state.append(knowledge)
    with pytest.raises(ValueError, match="exact dependency outputs"):
        StormWikiPipelineState(
            "agent research",
            (
                knowledge,
                StormWikiStageReceipt(
                    StormWikiStage.OUTLINE_GENERATION,
                    _digest("outline"),
                    (_digest("other-knowledge"),),
                ),
            ),
        )
