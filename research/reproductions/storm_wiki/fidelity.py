from __future__ import annotations

from dataclasses import dataclass


STORM_WIKI_AUDITED_COMMIT = "1f8ac2ddb4dd5f8cfcc250fdd3611c693098134b"


@dataclass(frozen=True, slots=True)
class StormWikiReferenceFidelity:
    """Paper-era STORM Wiki pipeline semantics audited from the official repository."""

    source_repository: str = "https://github.com/stanford-oval/storm"
    audited_commit: str = STORM_WIKI_AUDITED_COMMIT
    engine_source: str = "src/storm_wiki/engine.py"
    knowledge_curation_source: str = "src/storm_wiki/modules/knowledge_curation.py"
    persona_source: str = "src/storm_wiki/modules/persona_generator.py"
    outline_source: str = "src/storm_wiki/modules/outline_generation.py"
    article_source: str = "src/storm_wiki/modules/article_generation.py"
    polish_source: str = "src/storm_wiki/modules/article_polish.py"
    stage_order: tuple[str, ...] = (
        "knowledge_curation",
        "outline_generation",
        "article_generation",
        "article_polishing",
    )
    max_conversation_turns: int = 3
    max_perspectives: int = 3
    max_search_queries_per_turn: int = 3
    search_top_k: int = 3
    section_retrieve_top_k: int = 3
    max_threads: int = 10
    perspective_guided_question_asking: bool = True
    per_result_snippet_count: int = 1
    expert_information_word_limit: int = 1000
    recent_full_dialogue_turns_in_question_context: int = 4
    explicit_citation_grounding: bool = True
    stage_outputs_are_reusable: bool = True

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("STORM audited commit must be a git SHA")
        if self.stage_order != (
            "knowledge_curation",
            "outline_generation",
            "article_generation",
            "article_polishing",
        ):
            raise ValueError("STORM pipeline stage order drifted")
        if (
            self.max_conversation_turns,
            self.max_perspectives,
            self.max_search_queries_per_turn,
            self.search_top_k,
            self.section_retrieve_top_k,
            self.max_threads,
        ) != (3, 3, 3, 3, 3, 10):
            raise ValueError("STORM paper-era runner defaults drifted")
        if self.per_result_snippet_count != 1 or self.expert_information_word_limit != 1000:
            raise ValueError("STORM expert grounding semantics drifted")
        if self.recent_full_dialogue_turns_in_question_context != 4:
            raise ValueError("STORM dialogue context projection drifted")
        if not (
            self.perspective_guided_question_asking
            and self.explicit_citation_grounding
            and self.stage_outputs_are_reusable
        ):
            raise ValueError("STORM research pipeline semantics drifted")


STORM_WIKI_REFERENCE_FIDELITY = StormWikiReferenceFidelity()


__all__ = [
    "STORM_WIKI_AUDITED_COMMIT",
    "STORM_WIKI_REFERENCE_FIDELITY",
    "StormWikiReferenceFidelity",
]
