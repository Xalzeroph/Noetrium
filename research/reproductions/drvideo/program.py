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
from research.reproductions._support import JsonObject, JsonValue, canonical_digest, freeze_json, require_sha256, thaw_json

from collections.abc import Mapping, Sequence





from .fidelity import DRVIDEO_REFERENCE_FIDELITY
from .source import DRVIDEO_OFFICIAL_COMMIT


_RETRIEVAL_CAPABILITY = "data.semantic-similarity"
_VISUAL_AGENT = "drvideo.visual-augmenter"
_PLANNING_AGENT = "drvideo.planning-agent"
_INTERACTION_AGENT = "drvideo.interaction-agent"
_ANSWER_AGENT = "drvideo.answering-agent"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise TypeError(f"DrVideo {field} must be text")
    result = value.strip()
    if not allow_empty and not result:
        raise ValueError(f"DrVideo {field} must be non-empty text")
    return result


def _mapping(value: object, field: str) -> dict[str, JsonValue]:
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"DrVideo {field} must be an object")
    return decoded


def _rows(value: object, field: str) -> tuple[dict[str, JsonValue], ...]:
    decoded = thaw_json(value)
    if not isinstance(decoded, (tuple, list)):
        raise TypeError(f"DrVideo {field} must be a sequence")
    rows: list[dict[str, JsonValue]] = []
    for row in decoded:
        if not isinstance(row, dict):
            raise TypeError(f"DrVideo {field} rows must be objects")
        rows.append(row)
    return tuple(rows)


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"DrVideo {field} must be >= {minimum}")
    return value


def drvideo_initial_state(
    *,
    question: str,
    options: tuple[str, ...],
    document: tuple[JsonObject, ...],
    projection_digest: str,
    source_cut_digest: str,
    embedding_model_digest: str,
    retrieval_query_vector: Sequence[float],
    top_k: int = DRVIDEO_REFERENCE_FIDELITY.paper_initial_top_k,
    max_rounds: int = DRVIDEO_REFERENCE_FIDELITY.max_agent_rounds,
) -> JsonObject:
    if type(options) is not tuple or len(options) < 2:
        raise ValueError("DrVideo options must contain at least two choices")
    normalized_document: list[JsonObject] = []
    frame_ids: set[str] = set()
    for row in document:
        if not isinstance(row, Mapping):
            raise TypeError("DrVideo document rows must be objects")
        frame_id = _text(row.get("frame_id"), "document frame_id")
        if frame_id in frame_ids:
            raise ValueError("DrVideo document frame ids must be unique")
        frame_ids.add(frame_id)
        content_digest = require_sha256(
            row.get("content_digest"),
            "DrVideo document content_digest",
        )
        normalized_document.append(
            {
                "frame_id": frame_id,
                "text": _text(row.get("text"), "document text", allow_empty=True),
                "content_digest": content_digest,
            }
        )
    if type(top_k) is not int or top_k < 1:
        raise ValueError("DrVideo top_k must be positive")
    if top_k > len(normalized_document):
        raise ValueError("DrVideo top_k cannot exceed document size")
    if type(max_rounds) is not int or not 1 <= max_rounds <= 2:
        raise ValueError("DrVideo max_rounds must be 1 or 2")
    vector = tuple(float(value) for value in retrieval_query_vector)
    if not vector:
        raise ValueError("DrVideo retrieval query vector must be non-empty")

    return {
        "source_commit": DRVIDEO_OFFICIAL_COMMIT,
        "question": _text(question, "question"),
        "options": tuple(_text(value, "option") for value in options),
        "document": tuple(normalized_document),
        "projection_digest": require_sha256(
            projection_digest, "DrVideo projection_digest"
        ),
        "source_cut_digest": require_sha256(
            source_cut_digest, "DrVideo source_cut_digest"
        ),
        "embedding_model_digest": require_sha256(
            embedding_model_digest, "DrVideo embedding_model_digest"
        ),
        "retrieval_query_vector": vector,
        "top_k": top_k,
        "max_rounds": max_rounds,
        "retrieved_frame_ids": (),
        "caption_augmented_frame_ids": (),
        "vqa_augmented_frame_ids": (),
        "pending_augmentation_requests": (),
        "planning_explanation": "",
        "feedback_history": (),
        "round_index": 0,
        "final_answer": "",
        "final_reasoning": "",
    }


def _prepare_retrieval(request: MethodCall) -> MethodNodeResult:
    vector = request.state.get("retrieval_query_vector")
    if not isinstance(vector, Sequence) or isinstance(
        vector, (str, bytes, bytearray)
    ):
        raise TypeError("DrVideo retrieval query vector must be a sequence")
    return dict(
        value={
            "projection_digest": _text(
                request.state.get("projection_digest"), "projection_digest"
            ),
            "source_cut_digest": _text(
                request.state.get("source_cut_digest"), "source_cut_digest"
            ),
            "embedding_model_digest": _text(
                request.state.get("embedding_model_digest"),
                "embedding_model_digest",
            ),
            "vector": tuple(float(value) for value in vector),
            "metric": "cosine_similarity",
            "limit": _integer(request.state.get("top_k"), "top_k", minimum=1),
            "candidates": (),
        }
    )


def _record_retrieval(request: MethodCall) -> MethodNodeResult:
    result = _mapping(request.previous_value, "semantic retrieval result")
    for key in (
        "projection_digest",
        "source_cut_digest",
        "embedding_model_digest",
    ):
        if result.get(key) != request.state.get(key):
            raise ValueError(f"DrVideo semantic retrieval {key} drift")

    document = _rows(request.state.get("document"), "document")
    by_id = {
        _text(row.get("frame_id"), "document frame_id"): row
        for row in document
    }
    matches = _rows(result.get("matches", ()), "semantic matches")
    top_k = _integer(request.state.get("top_k"), "top_k", minimum=1)
    if not matches:
        raise RuntimeError("DrVideo retrieval returned no key frame")
    if len(matches) > top_k:
        raise ValueError("DrVideo retrieval exceeded configured Top-K")

    selected: list[str] = []
    for match in matches:
        frame_id = _text(match.get("record_id"), "retrieved frame id")
        document_row = by_id.get(frame_id)
        if document_row is None:
            raise ValueError("DrVideo retriever selected frame outside document")
        if match.get("content_digest") != document_row.get("content_digest"):
            raise ValueError("DrVideo retrieved frame provenance drift")
        if frame_id not in selected:
            selected.append(frame_id)

    return dict(
        value={"retrieved_frame_ids": tuple(selected)},
        state_update={"retrieved_frame_ids": tuple(selected)},
    )


def _document_view(request: MethodCall) -> tuple[JsonObject, ...]:
    return tuple(
        {
            "frame_id": _text(row.get("frame_id"), "document frame id"),
            "text": _text(row.get("text"), "document text", allow_empty=True),
        }
        for row in _rows(request.state.get("document"), "document")
    )


def _initial_augmentation_view(request: MethodCall) -> JsonObject:
    return {
        "phase": "initial_question_conditioned_augmentation",
        "question": _text(request.state.get("question"), "question"),
        "document": _document_view(request),
        "requests": tuple(
            {"frame_id": frame_id, "type": "vqa"}
            for frame_id in request.state.get("retrieved_frame_ids", ())
        ),
        "instruction": (
            "Augment each initially retrieved key frame with question-specific "
            "visual information before the planning loop."
        ),
    }


def _updates(value: object) -> tuple[dict[str, JsonValue], ...]:
    result = _mapping(value, "visual augmentation result")
    return _rows(result.get("updates", ()), "visual augmentation updates")


def _apply_updates(
    request: MethodCall,
    updates: tuple[dict[str, JsonValue], ...],
) -> tuple[tuple[JsonObject, ...], tuple[str, ...], tuple[str, ...]]:
    document = [
        dict(row) for row in _rows(request.state.get("document"), "document")
    ]
    by_id = {
        _text(row.get("frame_id"), "document frame id"): row
        for row in document
    }
    caption_ids = list(request.state.get("caption_augmented_frame_ids", ()))
    vqa_ids = list(request.state.get("vqa_augmented_frame_ids", ()))

    for update in updates:
        frame_id = _text(update.get("frame_id"), "augmentation frame_id")
        kind = _text(update.get("type"), "augmentation type")
        if kind not in {"caption", "vqa"}:
            raise ValueError("DrVideo augmentation type must be caption or vqa")
        text = _text(update.get("text"), "augmentation text")
        row = by_id.get(frame_id)
        if row is None:
            raise ValueError("DrVideo augmentation targeted unknown frame")
        row["text"] = (
            _text(row.get("text"), "document text", allow_empty=True)
            + f" [{kind}: {text}]"
        ).strip()
        target = caption_ids if kind == "caption" else vqa_ids
        if frame_id not in target:
            target.append(frame_id)

    return tuple(document), tuple(caption_ids), tuple(vqa_ids)


def _record_initial_augmentation(request: MethodCall) -> MethodNodeResult:
    updates = _updates(request.previous_value)
    selected = tuple(request.state.get("retrieved_frame_ids", ()))
    if {row.get("frame_id") for row in updates} != set(selected):
        raise ValueError(
            "DrVideo initial augmentation must cover every retrieved key frame"
        )
    if any(row.get("type") != "vqa" for row in updates):
        raise ValueError("DrVideo initial retrieved frames require VQA augmentation")
    document, caption_ids, vqa_ids = _apply_updates(request, updates)
    return dict(
        value={"augmented_frame_count": len(updates)},
        state_update={
            "document": document,
            "caption_augmented_frame_ids": caption_ids,
            "vqa_augmented_frame_ids": vqa_ids,
        },
    )


def _planning_view(request: MethodCall) -> JsonObject:
    return {
        "phase": "planning",
        "question": _text(request.state.get("question"), "question"),
        "document": _document_view(request),
        "feedback_history": tuple(
            thaw_json(row)
            for row in request.state.get("feedback_history", ())
        ),
        "round_index": _integer(request.state.get("round_index"), "round_index"),
        "max_rounds": _integer(request.state.get("max_rounds"), "max_rounds", minimum=1),
        "instruction": (
            "Judge whether the current document is sufficient to answer the "
            "question. Return confidence and an explanation of missing evidence."
        ),
    }


def _planning_decision(value: object) -> tuple[bool, str]:
    result = _mapping(value, "planning result")
    confidence = result.get("confidence")
    if confidence in {True, 1, "1"}:
        ready = True
    elif confidence in {False, 0, "0"}:
        ready = False
    else:
        raise ValueError("DrVideo planning confidence must be binary")
    explanation = result.get("explanation", "")
    if isinstance(explanation, (tuple, list)):
        explanation = " ".join(str(row) for row in explanation)
    return ready, _text(explanation, "planning explanation", allow_empty=True)


def _route_planning(request: MethodCall) -> MethodNodeResult:
    ready, explanation = _planning_decision(request.previous_value)
    if ready:
        return dict(
            value={"ready": True, "explanation": explanation},
            state_update={"planning_explanation": explanation},
            next_node="answer",
        )
    return dict(
        value={"ready": False, "explanation": explanation},
        state_update={"planning_explanation": explanation},
        next_node="interaction",
    )


def _interaction_view(request: MethodCall) -> JsonObject:
    return {
        "phase": "interaction",
        "question": _text(request.state.get("question"), "question"),
        "document": _document_view(request),
        "missing_information": _text(
            request.state.get("planning_explanation"),
            "planning explanation",
            allow_empty=True,
        ),
        "caption_augmented_frame_ids": tuple(
            request.state.get("caption_augmented_frame_ids", ())
        ),
        "vqa_augmented_frame_ids": tuple(
            request.state.get("vqa_augmented_frame_ids", ())
        ),
        "maximum_new_frames": (
            DRVIDEO_REFERENCE_FIDELITY.maximum_added_frames_per_round
        ),
        "augmentation_types": DRVIDEO_REFERENCE_FIDELITY.augmentation_types,
    }


def _record_interaction(request: MethodCall) -> MethodNodeResult:
    result = _mapping(request.previous_value, "interaction result")
    frames = _rows(result.get("frames", ()), "interaction frames")
    if len(frames) > DRVIDEO_REFERENCE_FIDELITY.maximum_added_frames_per_round:
        raise ValueError("DrVideo interaction selected too many frames")
    document_ids = {
        row["frame_id"] for row in _document_view(request)
    }
    caption_used = set(request.state.get("caption_augmented_frame_ids", ()))
    vqa_used = set(request.state.get("vqa_augmented_frame_ids", ()))
    normalized: list[JsonObject] = []
    seen: set[tuple[str, str]] = set()
    for row in frames:
        frame_id = _text(row.get("frame_id"), "interaction frame_id")
        kind = _text(row.get("type"), "interaction type")
        if kind not in {"caption", "vqa"}:
            raise ValueError("DrVideo interaction type must be caption or vqa")
        if frame_id not in document_ids:
            raise ValueError("DrVideo interaction selected unknown frame")
        key = (frame_id, kind)
        if key in seen:
            raise ValueError("DrVideo interaction duplicated a frame/type request")
        if (kind == "caption" and frame_id in caption_used) or (
            kind == "vqa" and frame_id in vqa_used
        ):
            raise ValueError("DrVideo interaction repeated existing frame/type information")
        seen.add(key)
        normalized.append({"frame_id": frame_id, "type": kind})

    if not normalized:
        return dict(
            value={"requests": ()},
            state_update={"pending_augmentation_requests": ()},
            next_node="answer",
        )
    return dict(
        value={"requests": tuple(normalized)},
        state_update={"pending_augmentation_requests": tuple(normalized)},
        next_node="augment",
    )


def _adaptive_augmentation_view(request: MethodCall) -> JsonObject:
    return {
        "phase": "adaptive_augmentation",
        "question": _text(request.state.get("question"), "question"),
        "document": _document_view(request),
        "requests": tuple(
            thaw_json(row)
            for row in request.state.get("pending_augmentation_requests", ())
        ),
        "planning_explanation": _text(
            request.state.get("planning_explanation"),
            "planning explanation",
            allow_empty=True,
        ),
    }


def _record_adaptive_augmentation(request: MethodCall) -> MethodNodeResult:
    updates = _updates(request.previous_value)
    pending = tuple(
        thaw_json(row)
        for row in request.state.get("pending_augmentation_requests", ())
    )
    expected = {
        (row.get("frame_id"), row.get("type")) for row in pending
    }
    actual = {
        (row.get("frame_id"), row.get("type")) for row in updates
    }
    if actual != expected:
        raise ValueError("DrVideo adaptive augmentation did not satisfy requests")

    document, caption_ids, vqa_ids = _apply_updates(request, updates)
    next_round = _integer(request.state.get("round_index"), "round_index") + 1
    history = (
        *tuple(
            thaw_json(row) for row in request.state.get("feedback_history", ())
        ),
        {
            "round": next_round,
            "planning_explanation": request.state.get("planning_explanation", ""),
            "updates": updates,
        },
    )
    max_rounds = _integer(request.state.get("max_rounds"), "max_rounds", minimum=1)
    return dict(
        value={"round": next_round, "augmented_frame_count": len(updates)},
        state_update={
            "document": document,
            "caption_augmented_frame_ids": caption_ids,
            "vqa_augmented_frame_ids": vqa_ids,
            "pending_augmentation_requests": (),
            "feedback_history": history,
            "round_index": next_round,
        },
        next_node="answer" if next_round >= max_rounds else "planning",
    )


def _answer_view(request: MethodCall) -> JsonObject:
    return {
        "phase": "answering",
        "question": _text(request.state.get("question"), "question"),
        "options": tuple(request.state.get("options", ())),
        "document": _document_view(request),
        "chain_of_thought": True,
        "instruction": "Reason over the final document and return the best option.",
    }


def _record_answer(request: MethodCall) -> MethodNodeResult:
    result = _mapping(request.previous_value, "answer result")
    answer = _text(result.get("answer"), "final answer")
    reasoning = _text(
        result.get("reasoning", ""), "final reasoning", allow_empty=True
    )
    return dict(
        value={"answer": answer, "reasoning": reasoning},
        state_update={
            "final_answer": answer,
            "final_reasoning": reasoning,
        },
    )


def _return_result(request: MethodCall) -> MethodNodeResult:
    return dict(
        value={
            "answer": _text(request.state.get("final_answer"), "final answer"),
            "reasoning": _text(
                request.state.get("final_reasoning"),
                "final reasoning",
                allow_empty=True,
            ),
            "retrieved_frame_ids": tuple(
                request.state.get("retrieved_frame_ids", ())
            ),
            "caption_augmented_frame_ids": tuple(
                request.state.get("caption_augmented_frame_ids", ())
            ),
            "vqa_augmented_frame_ids": tuple(
                request.state.get("vqa_augmented_frame_ids", ())
            ),
            "interaction_rounds": _integer(
                request.state.get("round_index"), "round_index"
            ),
            "final_document": _document_view(request),
        }
    )


def build_drvideo_method_program(method, ) -> None:
    fidelity = DRVIDEO_REFERENCE_FIDELITY
    configuration: JsonObject = {
        "paper": "CVPR 2025",
        "source_commit": DRVIDEO_OFFICIAL_COMMIT,
        "paper_top_k": fidelity.paper_initial_top_k,
        "official_code_top_k": fidelity.official_code_initial_top_k,
        "max_agent_rounds": fidelity.max_agent_rounds,
        "augmentation_types": fidelity.augmentation_types,
        "retrieval_metric": "cosine_similarity",
        "answering": "chain_of_thought",
    }

    loops = fidelity.max_agent_rounds
    builder = method
    builder.compute(
        "prepare_retrieval",
        "drvideo.document-retrieval.prepare",
        _prepare_retrieval,
        ("retrieve",),
    )
    builder.capability(
        "retrieve",
        "drvideo.document-retrieval.query",
        _RETRIEVAL_CAPABILITY,
        ("record_retrieval",),
        effect='pure',
        evidence=("drvideo.semantic-retrieval",),
    )
    builder.compute(
        "record_retrieval",
        "drvideo.document-retrieval.record",
        _record_retrieval,
        ("initial_augment",),
    )
    builder.agent(
        "initial_augment",
        "drvideo.document-augmentation.initial",
        _VISUAL_AGENT,
        ("record_initial_augment",),
        view=_initial_augmentation_view,
    )
    builder.compute(
        "record_initial_augment",
        "drvideo.document-augmentation.initial-record",
        _record_initial_augmentation,
        ("planning",),
    )
    builder.agent(
        "planning",
        "drvideo.agent.planning",
        _PLANNING_AGENT,
        ("route_planning",),
        view=_planning_view,
        max_visits=loops,
    )
    builder.route(
        "route_planning",
        "drvideo.agent.planning-route",
        _route_planning,
        ("interaction", "answer"),
        max_visits=loops,
    )
    builder.agent(
        "interaction",
        "drvideo.agent.interaction",
        _INTERACTION_AGENT,
        ("record_interaction",),
        view=_interaction_view,
        max_visits=loops,
    )
    builder.route(
        "record_interaction",
        "drvideo.agent.interaction-record",
        _record_interaction,
        ("augment", "answer"),
        max_visits=loops,
    )
    builder.agent(
        "augment",
        "drvideo.document-augmentation.adaptive",
        _VISUAL_AGENT,
        ("record_augment",),
        view=_adaptive_augmentation_view,
        max_visits=loops,
    )
    builder.route(
        "record_augment",
        "drvideo.document-augmentation.adaptive-record",
        _record_adaptive_augmentation,
        ("planning", "answer"),
        max_visits=loops,
    )
    builder.agent(
        "answer",
        "drvideo.answering.cot",
        _ANSWER_AGENT,
        ("record_answer",),
        view=_answer_view,
    )
    builder.compute(
        "record_answer",
        "drvideo.answering.record",
        _record_answer,
        ("return",),
    )
    builder.return_node("return", "drvideo.result", _return_result)
    builder.configure(configuration)
    builder.requires(*(_RETRIEVAL_CAPABILITY,))
    builder.policy(
        execution='effect_recorded',
        evidence=(
            "drvideo.semantic-retrieval",
            "drvideo.document-augmentation",
            "drvideo.agent-feedback",
            "model.invocation",
        ),
        metrics=(
            "task_success",
            "retrieved_frame_count",
            "augmented_frame_count",
            "interaction_rounds",
        ),
        artifacts=(
            "drvideo_document",
            "drvideo_feedback_trajectory",
        ),
    )
    return builder


METHOD_CONFIGURER = build_drvideo_method_program
METHOD_ENTRYPOINT = "prepare_retrieval"
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}


__all__ = [
    'build_drvideo_method_program',
    'drvideo_initial_state',
    'METHOD_CONFIGURER',
    'METHOD_ENTRYPOINT',
    'METHOD_CONFIGURER_ARGS',
    'METHOD_CONFIGURER_KWARGS',
]

METHOD_SPEC = {"method_id": 'drvideo', "version": "paper-protocol", "semantic_contract": 'drvideo' + ".method.v2", "entrypoint": METHOD_ENTRYPOINT}

__all__ = tuple(dict.fromkeys((*__all__, 'METHOD_SPEC')))
