from __future__ import annotations

from research.reproductions._support import (
    JsonObject,
    JsonValue,
    MethodCall,
    canonical_digest,
    freeze_json,
    method_event,
    require_sha256,
    thaw_json,
)
from research.reproductions._support import JsonObject, JsonValue, canonical_digest, thaw_json

from collections.abc import Mapping, Sequence





from .fidelity import STORM_WIKI_REFERENCE_FIDELITY
from .pipeline import STORM_WIKI_STAGE_ORDER

_PERSPECTIVE_AGENT = "storm.perspective-discovery"
_QUESTION_AGENT = "storm.question-asking"
_EXPERT_AGENT = "storm.topic-expert"
_OUTLINE_AGENT = "storm.outline-generation"
_ARTICLE_AGENT = "storm.article-generation"
_POLISH_AGENT = "storm.article-polishing"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
        raise ValueError(f"STORM {field} must be text")
    return value


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"STORM {field} must be a sequence")
    return tuple(value)


def storm_wiki_initial_state(*, topic: str) -> JsonObject:
    return {
        "topic": _text(topic, "topic"),
        "perspectives": (),
        "perspective_index": 0,
        "turn_index": 0,
        "pending_question": "",
        "pending_queries": (),
        "last_search_results": {},
        "conversation_log": (),
        "raw_search_results": (),
        "outline": "",
        "direct_outline": "",
        "article": "",
        "polished_article": "",
        "url_to_info": {},
        "model_call_count": 0,
        "search_call_count": 0,
    }


def _model_count(request: MethodCall) -> int:
    value = request.state.get("model_call_count", 0)
    if type(value) is not int or value < 0:
        raise ValueError("STORM model_call_count must be non-negative")
    return value


def _search_count(request: MethodCall) -> int:
    value = request.state.get("search_call_count", 0)
    if type(value) is not int or value < 0:
        raise ValueError("STORM search_call_count must be non-negative")
    return value


def _perspective_view(request: MethodCall) -> JsonObject:
    return {
        "topic": request.state.get("topic"),
        "objective": (
            "discover diverse perspectives that would guide researching the topic"
        ),
        "max_perspectives": STORM_WIKI_REFERENCE_FIDELITY.max_perspectives,
    }


def _record_perspectives(request: MethodCall) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, Mapping):
        raw = value.get("perspectives", ())
    else:
        raw = value
    rows = tuple(
        _text(row, "perspective")
        for row in _sequence(raw, "perspectives")
        if str(row).strip()
    )
    if not rows:
        raise ValueError("STORM perspective discovery returned no perspectives")
    rows = rows[: STORM_WIKI_REFERENCE_FIDELITY.max_perspectives]
    return dict(
        value={"perspectives": rows},
        state_update={
            "perspectives": rows,
            "perspective_index": 0,
            "turn_index": 0,
            "model_call_count": _model_count(request) + 1,
        },
        next_node="dialogue_route",
    )


def _perspectives(request: MethodCall) -> tuple[str, ...]:
    return tuple(
        _text(row, "perspective")
        for row in _sequence(request.state.get("perspectives", ()), "perspectives")
    )


def _dialogue_route(request: MethodCall) -> MethodNodeResult:
    perspectives = _perspectives(request)
    index = request.state.get("perspective_index", 0)
    turn = request.state.get("turn_index", 0)
    if type(index) is not int or index < 0:
        raise ValueError("STORM perspective_index must be non-negative")
    if type(turn) is not int or turn < 0:
        raise ValueError("STORM turn_index must be non-negative")
    if index >= len(perspectives):
        return dict(
            value={"knowledge_curation_complete": True},
            next_node="outline",
            checkpoint=True,
            checkpoint_value={
                "stage": STORM_WIKI_STAGE_ORDER[0].value,
                "conversation_count": len(
                    _sequence(
                        request.state.get("conversation_log", ()),
                        "conversation_log",
                    )
                ),
            },
        )
    return dict(
        value={
            "perspective": perspectives[index],
            "turn_index": turn,
        },
        next_node="question",
    )


def _question_view(request: MethodCall) -> JsonObject:
    perspectives = _perspectives(request)
    index = request.state.get("perspective_index", 0)
    if type(index) is not int or not 0 <= index < len(perspectives):
        raise ValueError("STORM question stage has invalid perspective index")
    log = _sequence(request.state.get("conversation_log", ()), "conversation_log")
    recent = log[
        -STORM_WIKI_REFERENCE_FIDELITY.recent_full_dialogue_turns_in_question_context :
    ]
    return {
        "topic": request.state.get("topic"),
        "perspective": perspectives[index],
        "turn_index": request.state.get("turn_index", 0),
        "recent_dialogue": recent,
        "max_search_queries": (
            STORM_WIKI_REFERENCE_FIDELITY.max_search_queries_per_turn
        ),
        "instruction": (
            "ask one useful perspective-guided question and propose search queries"
        ),
    }


def _record_question(request: MethodCall) -> MethodNodeResult:
    value = request.previous_value
    if not isinstance(value, Mapping):
        raise TypeError("STORM question output must be an object")
    question = _text(value.get("question"), "question")
    raw_queries = _sequence(value.get("queries", ()), "search queries")
    queries = tuple(
        _text(row, "search query") for row in raw_queries if str(row).strip()
    )
    limit = STORM_WIKI_REFERENCE_FIDELITY.max_search_queries_per_turn
    if not queries:
        queries = (question,)
    queries = queries[:limit]
    return dict(
        value={"question": question, "queries": queries},
        state_update={
            "pending_question": question,
            "pending_queries": queries,
            "model_call_count": _model_count(request) + 1,
        },
        next_node="prepare_search",
    )


def _prepare_search(request: MethodCall) -> MethodNodeResult:
    return dict(
        value={
            "topic": request.state.get("topic"),
            "question": request.state.get("pending_question"),
            "queries": request.state.get("pending_queries", ()),
            "top_k": STORM_WIKI_REFERENCE_FIDELITY.search_top_k,
            "snippet_count_per_result": (
                STORM_WIKI_REFERENCE_FIDELITY.per_result_snippet_count
            ),
        }
    )


def _record_search(request: MethodCall) -> MethodNodeResult:
    result = thaw_json(request.previous_value)
    rows = list(
        _sequence(
            request.state.get("raw_search_results", ()),
            "raw_search_results",
        )
    )
    rows.append({
        "question": request.state.get("pending_question"),
        "queries": request.state.get("pending_queries", ()),
        "result": result,
    })
    return dict(
        value={"search_result": result},
        state_update={
            "last_search_results": result,
            "raw_search_results": tuple(rows),
            "search_call_count": _search_count(request) + 1,
        },
        next_node="expert",
    )


def _expert_view(request: MethodCall) -> JsonObject:
    perspectives = _perspectives(request)
    index = request.state.get("perspective_index", 0)
    if type(index) is not int or not 0 <= index < len(perspectives):
        raise ValueError("STORM expert stage has invalid perspective index")
    return {
        "topic": request.state.get("topic"),
        "perspective": perspectives[index],
        "question": request.state.get("pending_question"),
        "search_results": request.state.get("last_search_results", {}),
        "word_limit": STORM_WIKI_REFERENCE_FIDELITY.expert_information_word_limit,
        "require_citation_grounding": (
            STORM_WIKI_REFERENCE_FIDELITY.explicit_citation_grounding
        ),
    }


def _record_expert(request: MethodCall) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, str):
        answer = value
        citations: JsonValue = ()
    elif isinstance(value, Mapping):
        answer = _text(value.get("answer", value.get("text", "")), "expert answer")
        citations = value.get("citations", ())
    else:
        raise TypeError("STORM expert output must be text or object")

    perspectives = _perspectives(request)
    p_index = request.state.get("perspective_index", 0)
    turn = request.state.get("turn_index", 0)
    if type(p_index) is not int or type(turn) is not int:
        raise TypeError("STORM dialogue indices must be integers")
    log = list(
        _sequence(request.state.get("conversation_log", ()), "conversation_log")
    )
    log.append({
        "perspective": perspectives[p_index],
        "turn_index": turn,
        "question": request.state.get("pending_question"),
        "answer": answer,
        "citations": citations,
    })

    next_turn = turn + 1
    next_perspective = p_index
    if next_turn >= STORM_WIKI_REFERENCE_FIDELITY.max_conversation_turns:
        next_perspective += 1
        next_turn = 0
    return dict(
        value={"answer": answer, "citations": citations},
        state_update={
            "conversation_log": tuple(log),
            "perspective_index": next_perspective,
            "turn_index": next_turn,
            "pending_question": "",
            "pending_queries": (),
            "model_call_count": _model_count(request) + 1,
        },
        next_node="dialogue_route",
        checkpoint=True,
        checkpoint_value={
            "stage": STORM_WIKI_STAGE_ORDER[0].value,
            "perspective_index": next_perspective,
            "turn_index": next_turn,
        },
    )


def _outline_view(request: MethodCall) -> JsonObject:
    return {
        "topic": request.state.get("topic"),
        "conversation_log": request.state.get("conversation_log", ()),
        "raw_search_results": request.state.get("raw_search_results", ()),
        "instruction": "synthesize a grounded hierarchical article outline",
    }


def _record_outline(request: MethodCall) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, str):
        outline = value
        direct = ""
    elif isinstance(value, Mapping):
        outline = _text(
            value.get("outline", value.get("storm_outline", "")),
            "outline",
        )
        direct_raw = value.get("direct_outline", "")
        direct = _text(direct_raw, "direct outline", allow_empty=True)
    else:
        raise TypeError("STORM outline output must be text or object")
    return dict(
        value={"outline": outline, "direct_outline": direct},
        state_update={
            "outline": outline,
            "direct_outline": direct,
            "model_call_count": _model_count(request) + 1,
        },
        next_node="article",
        checkpoint=True,
        checkpoint_value={
            "stage": STORM_WIKI_STAGE_ORDER[1].value,
            "outline_digest": canonical_digest(outline),
        },
    )


def _article_view(request: MethodCall) -> JsonObject:
    return {
        "topic": request.state.get("topic"),
        "outline": request.state.get("outline"),
        "conversation_log": request.state.get("conversation_log", ()),
        "raw_search_results": request.state.get("raw_search_results", ()),
        "section_retrieve_top_k": (
            STORM_WIKI_REFERENCE_FIDELITY.section_retrieve_top_k
        ),
        "require_inline_citations": (
            STORM_WIKI_REFERENCE_FIDELITY.explicit_citation_grounding
        ),
    }


def _record_article(request: MethodCall) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, str):
        article = value
        url_to_info: JsonValue = {}
    elif isinstance(value, Mapping):
        article = _text(value.get("article", value.get("text", "")), "article")
        url_to_info = value.get("url_to_info", {})
    else:
        raise TypeError("STORM article output must be text or object")
    return dict(
        value={"article": article, "url_to_info": url_to_info},
        state_update={
            "article": article,
            "url_to_info": url_to_info,
            "model_call_count": _model_count(request) + 1,
        },
        next_node="polish",
        checkpoint=True,
        checkpoint_value={
            "stage": STORM_WIKI_STAGE_ORDER[2].value,
            "article_digest": canonical_digest(article),
        },
    )


def _polish_view(request: MethodCall) -> JsonObject:
    return {
        "topic": request.state.get("topic"),
        "article": request.state.get("article"),
        "outline": request.state.get("outline"),
        "url_to_info": request.state.get("url_to_info", {}),
        "instruction": (
            "polish the article while preserving grounded citation references"
        ),
    }


def _record_polish(request: MethodCall) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, str):
        article = value
    elif isinstance(value, Mapping):
        article = _text(
            value.get("polished_article", value.get("article", value.get("text", ""))),
            "polished article",
        )
    else:
        raise TypeError("STORM polishing output must be text or object")
    return dict(
        value={"polished_article": article},
        state_update={
            "polished_article": article,
            "model_call_count": _model_count(request) + 1,
        },
        next_node="return",
        checkpoint=True,
        checkpoint_value={
            "stage": STORM_WIKI_STAGE_ORDER[3].value,
            "polished_article_digest": canonical_digest(article),
        },
    )


def _return_result(request: MethodCall) -> MethodNodeResult:
    return dict(
        value={
            "topic": request.state.get("topic"),
            "perspectives": request.state.get("perspectives", ()),
            "conversation_log": request.state.get("conversation_log", ()),
            "outline": request.state.get("outline", ""),
            "direct_outline": request.state.get("direct_outline", ""),
            "article": request.state.get("article", ""),
            "polished_article": request.state.get("polished_article", ""),
            "url_to_info": request.state.get("url_to_info", {}),
            "model_call_count": request.state.get("model_call_count", 0),
            "search_call_count": request.state.get("search_call_count", 0),
        }
    )


def build_storm_wiki_method_program(method,
    *,
    search_capability_id: str,
) -> None:
    search_capability_id = _text(search_capability_id, "search capability id")
    fidelity = STORM_WIKI_REFERENCE_FIDELITY
    configuration: JsonObject = {
        "source_commit": fidelity.audited_commit,
        "stage_order": fidelity.stage_order,
        "max_perspectives": fidelity.max_perspectives,
        "max_conversation_turns": fidelity.max_conversation_turns,
        "max_search_queries_per_turn": fidelity.max_search_queries_per_turn,
        "search_top_k": fidelity.search_top_k,
        "section_retrieve_top_k": fidelity.section_retrieve_top_k,
        "search_capability_id": search_capability_id,
    }

    dialogue_bound = (
        fidelity.max_perspectives * fidelity.max_conversation_turns
    )
    builder = method
    builder.agent(
        "perspectives",
        "storm.knowledge-curation.perspectives",
        _PERSPECTIVE_AGENT,
        ("record_perspectives",),
        view=_perspective_view,
    )
    builder.compute(
        "record_perspectives",
        "storm.knowledge-curation.perspectives-record",
        _record_perspectives,
        ("dialogue_route",),
    )
    builder.route(
        "dialogue_route",
        "storm.knowledge-curation.dialogue-route",
        _dialogue_route,
        ("question", "outline"),
        max_visits=dialogue_bound + 1,
    )
    builder.agent(
        "question",
        "storm.knowledge-curation.question",
        _QUESTION_AGENT,
        ("record_question",),
        view=_question_view,
        max_visits=dialogue_bound,
    )
    builder.compute(
        "record_question",
        "storm.knowledge-curation.question-record",
        _record_question,
        ("prepare_search",),
        max_visits=dialogue_bound,
    )
    builder.compute(
        "prepare_search",
        "storm.knowledge-curation.search-prepare",
        _prepare_search,
        ("search",),
        max_visits=dialogue_bound,
    )
    builder.capability(
        "search",
        "storm.knowledge-curation.search",
        search_capability_id,
        ("record_search",),
        effect='pure',
        max_visits=dialogue_bound,
        evidence=("storm.search-evidence",),
    )
    builder.compute(
        "record_search",
        "storm.knowledge-curation.search-record",
        _record_search,
        ("expert",),
        max_visits=dialogue_bound,
    )
    builder.agent(
        "expert",
        "storm.knowledge-curation.expert",
        _EXPERT_AGENT,
        ("record_expert",),
        view=_expert_view,
        max_visits=dialogue_bound,
    )
    builder.compute(
        "record_expert",
        "storm.knowledge-curation.expert-record",
        _record_expert,
        ("dialogue_route",),
        max_visits=dialogue_bound,
    )
    builder.agent(
        "outline",
        "storm.outline-generation",
        _OUTLINE_AGENT,
        ("record_outline",),
        view=_outline_view,
    )
    builder.compute(
        "record_outline",
        "storm.outline-generation.record",
        _record_outline,
        ("article",),
    )
    builder.agent(
        "article",
        "storm.article-generation",
        _ARTICLE_AGENT,
        ("record_article",),
        view=_article_view,
    )
    builder.compute(
        "record_article",
        "storm.article-generation.record",
        _record_article,
        ("polish",),
    )
    builder.agent(
        "polish",
        "storm.article-polishing",
        _POLISH_AGENT,
        ("record_polish",),
        view=_polish_view,
    )
    builder.compute(
        "record_polish",
        "storm.article-polishing.record",
        _record_polish,
        ("return",),
    )
    builder.return_node("return", "storm.result", _return_result)
    builder.configure(configuration)
    builder.requires(*(search_capability_id,))
    builder.policy(
        execution='checkpointable',
        evidence=(
            "storm.search-evidence",
            "storm.conversation-log",
            "storm.outline",
            "storm.article",
            "storm.citation-grounding",
        ),
        metrics=(
            "heading_soft_recall",
            "heading_entity_recall",
            "rouge",
            "entity_recall",
            "rubric_score",
            "model_call_count",
            "search_call_count",
        ),
        artifacts=(
            "storm_conversation_log",
            "storm_raw_search_results",
            "storm_outline",
            "storm_article",
            "storm_polished_article",
        ),
    )
    return builder


METHOD_CONFIGURER = build_storm_wiki_method_program
METHOD_ENTRYPOINT = "perspectives"
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = [
    'build_storm_wiki_method_program',
    'storm_wiki_initial_state',
    'METHOD_CONFIGURER',
    'METHOD_ENTRYPOINT',
    'METHOD_CONFIGURER_ARGS',
    'METHOD_CONFIGURER_KWARGS',
]

METHOD_SPEC = {"method_id": 'storm', "version": "paper-protocol", "semantic_contract": 'storm' + ".method.v2", "entrypoint": METHOD_ENTRYPOINT}

__all__ = tuple(dict.fromkeys((*__all__, 'METHOD_SPEC')))
