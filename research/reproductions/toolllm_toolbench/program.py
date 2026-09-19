from __future__ import annotations

from collections.abc import Mapping, Sequence
import json

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY
from .search import ToolLLMObservationStatus

_POLICY_AGENT_ID = "toolllm.dfsdt-policy"
_SEMANTIC_CAPABILITY = "data.semantic-similarity"
_FINISH_NAME = "Finish"
_RETRIEVAL_MODES = ("oracle", "retrieved-top5")


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"ToolLLM {field} must be text")
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"ToolLLM {field} must be a non-negative integer")
    return value


def _sequence(value: object, field: str) -> tuple[JsonValue, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"ToolLLM {field} must be a sequence")
    return tuple(freeze_json(row) for row in value)


def _finish_schema() -> JsonObject:
    return {
        "name": "Finish",
        "description": (
            "If you believe that you have obtained a result that can answer the task, "
            "call this function to provide the final answer. If you are unable to "
            "proceed in the current state, call it to restart. Always call Finish at "
            "the end of the attempt."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "return_type": {
                    "type": "string",
                    "enum": ("give_answer", "give_up_and_restart"),
                },
                "final_answer": {
                    "type": "string",
                    "description": (
                        "Final answer shown to the user when return_type is give_answer."
                    ),
                },
            },
            "required": ("return_type",),
        },
    }


def _catalog(
    value: object,
    *,
    allowed_capability_ids: tuple[str, ...],
) -> tuple[JsonObject, ...]:
    rows = _sequence(value, "tool_catalog")
    allowed = set(allowed_capability_ids)
    parsed: list[JsonObject] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise TypeError("ToolLLM tool catalog rows must be mappings")
        capability_id = _text(raw.get("capability_id"), "catalog capability_id")
        if capability_id not in allowed:
            raise ValueError(
                f"ToolLLM tool catalog escaped program capability closure: {capability_id!r}"
            )
        if capability_id in seen:
            raise ValueError(f"ToolLLM duplicate tool capability: {capability_id!r}")
        seen.add(capability_id)
        descriptor_digest = _text(
            raw.get("descriptor_digest"),
            "catalog descriptor_digest",
        )
        require_sha256(descriptor_digest, "ToolLLM descriptor_digest")
        schema = raw.get("function_schema")
        if not isinstance(schema, Mapping):
            raise TypeError("ToolLLM function_schema must be a mapping")
        schema_name = _text(schema.get("name"), "function schema name")
        if schema_name != capability_id:
            raise ValueError(
                "ToolLLM capability id must equal paper-era materialized function name"
            )
        parsed.append(
            {
                "capability_id": capability_id,
                "descriptor_digest": descriptor_digest,
                "function_schema": freeze_json(schema),
            }
        )
    if not parsed:
        raise ValueError("ToolLLM tool catalog cannot be empty")
    return tuple(sorted(parsed, key=lambda row: str(row["capability_id"])))


def _catalog_index(state: Mapping[str, JsonValue]) -> dict[str, JsonObject]:
    rows = state.get("tool_catalog", ())
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise TypeError("ToolLLM tool_catalog state must be a sequence")
    result: dict[str, JsonObject] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise TypeError("ToolLLM tool catalog state row must be a mapping")
        capability_id = _text(raw.get("capability_id"), "catalog capability_id")
        result[capability_id] = freeze_json(dict(raw))
    return result


def _frame(value: object) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError("ToolLLM DFS frame must be a mapping")
    return {
        "frame_id": _text(value.get("frame_id"), "frame_id"),
        "tree_depth": _integer(value.get("tree_depth"), "tree_depth"),
        "trajectory": _sequence(value.get("trajectory", ()), "trajectory"),
        "next_sibling": _integer(value.get("next_sibling", 0), "next_sibling"),
        "siblings": _sequence(value.get("siblings", ()), "siblings"),
    }


def _frames(state: Mapping[str, JsonValue]) -> tuple[JsonObject, ...]:
    return tuple(_frame(row) for row in _sequence(state.get("frames", ()), "frames"))


def _top_frame(state: Mapping[str, JsonValue]) -> JsonObject:
    frames = _frames(state)
    if not frames:
        raise RuntimeError("ToolLLM DFS stack is empty")
    return frames[-1]


def toolllm_toolbench_initial_state(
    *,
    task_id: str,
    task_instruction: str,
    tool_catalog: tuple[Mapping[str, object], ...],
    allowed_capability_ids: tuple[str, ...],
    retrieval_mode: str = "oracle",
    oracle_tool_ids: tuple[str, ...] = (),
    retrieval_query_vector: tuple[float, ...] = (),
    projection_digest: str | None = None,
    source_cut_digest: str | None = None,
    embedding_model_digest: str | None = None,
) -> JsonObject:
    if retrieval_mode not in _RETRIEVAL_MODES:
        raise ValueError(f"unsupported ToolLLM retrieval mode: {retrieval_mode!r}")
    if type(allowed_capability_ids) is not tuple or not allowed_capability_ids:
        raise ValueError("ToolLLM allowed capability closure cannot be empty")
    if len(set(allowed_capability_ids)) != len(allowed_capability_ids):
        raise ValueError("ToolLLM allowed capability closure must be unique")
    catalog = _catalog(
        tool_catalog,
        allowed_capability_ids=allowed_capability_ids,
    )
    known = {str(row["capability_id"]) for row in catalog}

    if retrieval_mode == "oracle":
        if type(oracle_tool_ids) is not tuple or not oracle_tool_ids:
            raise ValueError("ToolLLM oracle mode requires oracle_tool_ids")
        if any(tool_id not in known for tool_id in oracle_tool_ids):
            raise ValueError("ToolLLM oracle tool escaped catalog")
        selected = tuple(dict.fromkeys(oracle_tool_ids))
    else:
        selected = ()
        if not retrieval_query_vector:
            raise ValueError("ToolLLM retrieved-top5 mode requires query vector")
        for field_name, value in (
            ("projection_digest", projection_digest),
            ("source_cut_digest", source_cut_digest),
            ("embedding_model_digest", embedding_model_digest),
        ):
            if not isinstance(value, str):
                raise ValueError(f"ToolLLM retrieved-top5 mode requires {field_name}")
            require_sha256(value, f"ToolLLM {field_name}")

    return {
        "task_id": _text(task_id, "task_id"),
        "task_instruction": _text(task_instruction, "task_instruction"),
        "retrieval_mode": retrieval_mode,
        "tool_catalog": catalog,
        "selected_tool_ids": selected,
        "retrieval_query_vector": tuple(float(row) for row in retrieval_query_vector),
        "projection_digest": projection_digest,
        "source_cut_digest": source_cut_digest,
        "embedding_model_digest": embedding_model_digest,
        "frames": (
            {
                "frame_id": "root",
                "tree_depth": 0,
                "trajectory": (),
                "next_sibling": 0,
                "siblings": (),
            },
        ),
        "query_count": 0,
        "tool_call_count": 0,
        "explored": (),
        "terminal": (),
        "give_up": (),
        "current_candidate": {},
        "budget_exhausted": False,
        "final_answer": "",
        "finish_type": "",
    }


def _prepare_retrieval(request: MethodNodeRequest) -> MethodNodeResult:
    if request.state.get("retrieval_mode") != "retrieved-top5":
        return MethodNodeResult(value={"retrieval": "not-required"}, next_node="policy")
    vector = request.state.get("retrieval_query_vector")
    if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes, bytearray)):
        raise TypeError("ToolLLM retrieval query vector must be a sequence")
    return MethodNodeResult(
        value={
            "projection_digest": _text(
                request.state.get("projection_digest"),
                "projection_digest",
            ),
            "source_cut_digest": _text(
                request.state.get("source_cut_digest"),
                "source_cut_digest",
            ),
            "embedding_model_digest": _text(
                request.state.get("embedding_model_digest"),
                "embedding_model_digest",
            ),
            "vector": tuple(float(row) for row in vector),
            "metric": "cosine_similarity",
            "limit": TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.default_retrieved_api_count,
            "candidates": (),
        },
        next_node="retrieve",
    )


def _record_retrieval(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    if not isinstance(value, Mapping):
        raise TypeError("ToolLLM semantic retrieval result must be a mapping")
    if value.get("projection_digest") != request.state.get("projection_digest"):
        raise ValueError("ToolLLM semantic retrieval projection drift")
    if value.get("source_cut_digest") != request.state.get("source_cut_digest"):
        raise ValueError("ToolLLM semantic retrieval source cut drift")
    if value.get("embedding_model_digest") != request.state.get("embedding_model_digest"):
        raise ValueError("ToolLLM semantic retrieval model drift")

    catalog = _catalog_index(request.state)
    matches = _sequence(value.get("matches", ()), "semantic matches")
    selected: list[str] = []
    for raw in matches:
        if not isinstance(raw, Mapping):
            raise TypeError("ToolLLM semantic match must be a mapping")
        capability_id = _text(raw.get("record_id"), "semantic match record_id")
        content_digest = _text(
            raw.get("content_digest"),
            "semantic match content_digest",
        )
        row = catalog.get(capability_id)
        if row is None:
            raise ValueError("ToolLLM retriever selected capability outside catalog")
        if row.get("descriptor_digest") != content_digest:
            raise ValueError("ToolLLM retriever descriptor provenance drift")
        selected.append(capability_id)
    if not selected:
        raise RuntimeError("ToolLLM retriever returned no materializable API")
    if len(selected) > TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.default_retrieved_api_count:
        raise ValueError("ToolLLM retriever exceeded paper top-k")
    return MethodNodeResult(
        value={"selected_tool_ids": tuple(selected)},
        state_update={"selected_tool_ids": tuple(selected)},
        next_node="policy",
    )


def _selected_schemas(state: Mapping[str, JsonValue]) -> tuple[JsonValue, ...]:
    selected = _sequence(state.get("selected_tool_ids", ()), "selected_tool_ids")
    catalog = _catalog_index(state)
    schemas: list[JsonValue] = []
    for raw_id in selected:
        capability_id = _text(raw_id, "selected tool id")
        try:
            row = catalog[capability_id]
        except KeyError as exc:
            raise ValueError("ToolLLM selected tool escaped catalog") from exc
        schemas.append(row["function_schema"])
    schemas.append(_finish_schema())
    return tuple(schemas)


def _policy_view(request: MethodNodeRequest) -> JsonObject:
    frame = _top_frame(request.state)
    return {
        "task_instruction": _text(
            request.state.get("task_instruction"),
            "task_instruction",
        ),
        "trajectory": frame["trajectory"],
        "previous_siblings": frame["siblings"],
        "functions": _selected_schemas(request.state),
        "query_count": _integer(request.state.get("query_count", 0), "query_count"),
        "max_query_count": TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.max_query_count,
        "tree_depth": frame["tree_depth"],
        "single_chain_max_step": (
            TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.single_chain_max_step
        ),
        "diversity_required": bool(frame["siblings"]),
        "search_policy": TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.reference_inference_method,
    }


def _candidate(value: JsonValue) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError("ToolLLM policy result must be a mapping")
    thought_value = value.get("thought", value.get("content", ""))
    thought = _text(thought_value, "candidate thought", allow_empty=True)
    action_name_raw = value.get("action_name", value.get("function_name"))
    action_name = (
        None
        if action_name_raw is None
        else _text(action_name_raw, "candidate action_name")
    )
    raw_input = value.get("action_input", value.get("arguments", ""))
    if isinstance(raw_input, Mapping):
        action_input = json.dumps(
            dict(raw_input),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    else:
        action_input = _text(raw_input, "candidate action_input", allow_empty=True)
    if action_name is None and action_input:
        raise ValueError("ToolLLM action_input requires action_name")
    if not thought and action_name is None:
        raise ValueError("ToolLLM candidate requires thought or action")
    parse_error = value.get("parse_error_code", 0)
    if type(parse_error) is not int or parse_error < 0:
        raise ValueError("ToolLLM parse_error_code must be non-negative integer")
    return {
        "thought": thought,
        "action_name": action_name,
        "action_input": action_input,
        "parse_error_code": parse_error,
    }


def _candidate_depth(parent_depth: int, candidate: Mapping[str, JsonValue]) -> int:
    return (
        parent_depth
        + (1 if bool(candidate.get("thought")) else 0)
        + (2 if candidate.get("action_name") is not None else 0)
    )


def _trace(
    parent: Sequence[JsonValue],
    candidate: Mapping[str, JsonValue],
    *,
    observation: str | None = None,
    status: int | None = None,
    visible_action_name: str | None = None,
) -> tuple[JsonValue, ...]:
    rows = list(parent)
    thought = candidate.get("thought")
    if isinstance(thought, str) and thought:
        rows.append({"kind": "Thought", "content": thought})
    action_name = candidate.get("action_name")
    if isinstance(action_name, str):
        rows.append(
            {
                "kind": "Action",
                "content": visible_action_name or action_name,
            }
        )
        if observation is None or status is None:
            raise ValueError("ToolLLM action trace requires observation and status")
        rows.append(
            {
                "kind": "Action Input",
                "content": _text(
                    candidate.get("action_input", ""),
                    "trace action_input",
                    allow_empty=True,
                ),
                "observation": observation,
                "observation_status": status,
            }
        )
    return tuple(freeze_json(row) for row in rows)


def _replace_top_frame(
    frames: tuple[JsonObject, ...],
    update: Mapping[str, JsonValue],
) -> tuple[JsonObject, ...]:
    if not frames:
        raise RuntimeError("ToolLLM cannot update empty DFS stack")
    top = dict(frames[-1])
    top.update(update)
    return (*frames[:-1], freeze_json(top))


def _advance_after_child(
    state: Mapping[str, JsonValue],
    *,
    child_trajectory: tuple[JsonValue, ...],
    child_depth: int,
    force_leaf: bool = False,
) -> MethodNodeResult:
    frames = _frames(state)
    top = frames[-1]
    siblings = (*_sequence(top.get("siblings", ()), "frame siblings"), child_trajectory)
    next_sibling = _integer(top.get("next_sibling", 0), "next_sibling") + 1
    frames = _replace_top_frame(
        frames,
        {
            "siblings": siblings,
            "next_sibling": next_sibling,
        },
    )
    explored = (*_sequence(state.get("explored", ()), "explored"), child_trajectory)

    if (
        not force_leaf
        and child_depth < TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.single_chain_max_step
    ):
        child_id = f"dfs:{len(explored)}:{child_depth}"
        frames = (
            *frames,
            {
                "frame_id": child_id,
                "tree_depth": child_depth,
                "trajectory": child_trajectory,
                "next_sibling": 0,
                "siblings": (),
            },
        )
        return MethodNodeResult(
            value={"descend": child_id, "tree_depth": child_depth},
            state_update={"frames": frames, "explored": explored},
            next_node="policy",
        )

    while frames and _integer(
        frames[-1].get("next_sibling", 0),
        "next_sibling",
    ) >= TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.tree_beam_size:
        frames = frames[:-1]
    return MethodNodeResult(
        value={"leaf": True, "tree_depth": child_depth},
        state_update={"frames": frames, "explored": explored},
        next_node="policy" if frames else "return",
    )


def _record_generation(request: MethodNodeRequest) -> MethodNodeResult:
    candidate = _candidate(request.previous_value)
    query_count = _integer(request.state.get("query_count", 0), "query_count") + 1
    update: JsonObject = {
        "query_count": query_count,
        "current_candidate": candidate,
    }
    if query_count >= TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.max_query_count:
        update["budget_exhausted"] = True
        return MethodNodeResult(
            value={"budget_exhausted": True, "query_count": query_count},
            state_update=update,
            next_node="return",
        )

    action_name = candidate.get("action_name")
    if action_name is None:
        return MethodNodeResult(
            value={"candidate": "thought-only"},
            state_update=update,
            next_node="commit_thought",
        )
    if action_name == _FINISH_NAME:
        return MethodNodeResult(
            value={"candidate": "finish"},
            state_update=update,
            next_node="finish",
        )

    selected = {
        _text(row, "selected tool id")
        for row in _sequence(
            request.state.get("selected_tool_ids", ()),
            "selected_tool_ids",
        )
    }
    if action_name not in selected:
        return MethodNodeResult(
            value={"candidate": "hallucinated-function", "action_name": action_name},
            state_update=update,
            next_node="hallucination",
        )
    return MethodNodeResult(
        value={"candidate": "tool-call", "action_name": action_name},
        state_update=update,
        next_node="prepare_tool",
    )


def _commit_thought(request: MethodNodeRequest) -> MethodNodeResult:
    candidate = request.state.get("current_candidate")
    if not isinstance(candidate, Mapping):
        raise TypeError("ToolLLM current candidate must be a mapping")
    frame = _top_frame(request.state)
    trajectory = _trace(
        _sequence(frame.get("trajectory", ()), "trajectory"),
        candidate,
    )
    child_depth = _candidate_depth(
        _integer(frame.get("tree_depth", 0), "tree_depth"),
        candidate,
    )
    return _advance_after_child(
        request.state,
        child_trajectory=trajectory,
        child_depth=child_depth,
        force_leaf=_integer(candidate.get("parse_error_code", 0), "parse_error_code") != 0,
    )


def _hallucination(request: MethodNodeRequest) -> MethodNodeResult:
    candidate = request.state.get("current_candidate")
    if not isinstance(candidate, Mapping):
        raise TypeError("ToolLLM current candidate must be a mapping")
    frame = _top_frame(request.state)
    action_name = _text(candidate.get("action_name"), "hallucinated action_name")
    observation = json.dumps(
        {
            "error": f"No such function name: {action_name}",
            "response": "",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    trajectory = _trace(
        _sequence(frame.get("trajectory", ()), "trajectory"),
        candidate,
        observation=observation,
        status=int(ToolLLMObservationStatus.HALLUCINATED_FUNCTION),
        visible_action_name="invalid_hallucination_function_name",
    )
    child_depth = _candidate_depth(
        _integer(frame.get("tree_depth", 0), "tree_depth"),
        candidate,
    )
    return _advance_after_child(
        request.state,
        child_trajectory=trajectory,
        child_depth=child_depth,
    )


def _prepare_tool(request: MethodNodeRequest) -> MethodNodeResult:
    candidate = request.state.get("current_candidate")
    if not isinstance(candidate, Mapping):
        raise TypeError("ToolLLM current candidate must be a mapping")
    action_name = _text(candidate.get("action_name"), "action_name")
    return MethodNodeResult(
        value={
            "function_name": action_name,
            "arguments": _text(
                candidate.get("action_input", ""),
                "action_input",
                allow_empty=True,
            ),
        }
    )


def _tool_target(request: MethodNodeRequest) -> str:
    candidate = request.state.get("current_candidate")
    if not isinstance(candidate, Mapping):
        raise TypeError("ToolLLM current candidate must be a mapping")
    action_name = _text(candidate.get("action_name"), "action_name")
    selected = {
        _text(row, "selected tool id")
        for row in _sequence(
            request.state.get("selected_tool_ids", ()),
            "selected_tool_ids",
        )
    }
    if action_name not in selected:
        raise ValueError("ToolLLM dynamic tool target escaped selected API view")
    return action_name


def _tool_observation(value: JsonValue) -> tuple[str, ToolLLMObservationStatus]:
    if not isinstance(value, Mapping):
        raise TypeError("ToolLLM tool result must be a mapping")
    content_value = value.get("content", value.get("observation", value.get("response")))
    if isinstance(content_value, str):
        content = content_value
    else:
        content = json.dumps(
            freeze_json(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    status_value = value.get("status", value.get("observation_code", 0))
    if type(status_value) is not int:
        raise TypeError("ToolLLM tool observation status must be integer")
    try:
        status = ToolLLMObservationStatus(status_value)
    except ValueError as exc:
        raise ValueError(
            f"unsupported ToolLLM observation status: {status_value}"
        ) from exc
    return content, status


def _record_tool(request: MethodNodeRequest) -> MethodNodeResult:
    candidate = request.state.get("current_candidate")
    if not isinstance(candidate, Mapping):
        raise TypeError("ToolLLM current candidate must be a mapping")
    content, status = _tool_observation(request.previous_value)
    frame = _top_frame(request.state)
    trajectory = _trace(
        _sequence(frame.get("trajectory", ()), "trajectory"),
        candidate,
        observation=content,
        status=int(status),
    )
    child_depth = _candidate_depth(
        _integer(frame.get("tree_depth", 0), "tree_depth"),
        candidate,
    )
    tool_calls = _integer(
        request.state.get("tool_call_count", 0),
        "tool_call_count",
    ) + 1
    state = dict(request.state)
    state["tool_call_count"] = tool_calls
    result = _advance_after_child(
        state,
        child_trajectory=trajectory,
        child_depth=child_depth,
    )
    return MethodNodeResult(
        value=result.value,
        state_update={**dict(result.state_update), "tool_call_count": tool_calls},
        next_node=result.next_node,
        checkpoint=result.checkpoint,
        checkpoint_value=result.checkpoint_value,
    )


def _finish_input(candidate: Mapping[str, JsonValue]) -> tuple[str, str]:
    """Mirror the released RapidAPI wrapper lenient Finish parsing."""

    raw = _text(
        candidate.get("action_input", ""),
        "Finish action_input",
        allow_empty=True,
    )
    parsed: dict[str, object]
    try:
        value = json.loads(raw, strict=False) if raw else {}
        parsed = dict(value) if isinstance(value, Mapping) else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        parsed = {}
        marker = '"return_type": "'
        if marker in raw:
            if '"return_type": "give_answer"' in raw:
                parsed["return_type"] = "give_answer"
            elif '"return_type": "give_up_and_restart"' in raw:
                parsed["return_type"] = "give_up_and_restart"
            else:
                marker_start = raw.find(marker) + len(marker)
                marker_end = raw.find('",', marker_start)
                parsed["return_type"] = (
                    raw[marker_start:]
                    if marker_end < 0
                    else raw[marker_start:marker_end]
                )
        answer_marker = '"final_answer": "'
        if answer_marker in raw:
            answer_start = raw.find(answer_marker) + len(answer_marker)
            parsed["final_answer"] = raw[answer_start:]

    return_type = parsed.get("return_type")
    if not isinstance(return_type, str) or not return_type.strip():
        raise ValueError("ToolLLM Finish requires return_type")
    if return_type not in TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.finish_return_types:
        raise ValueError("ToolLLM Finish return_type drifted")
    final_answer = parsed.get("final_answer", "")
    if not isinstance(final_answer, str):
        raise TypeError("ToolLLM Finish final_answer must be text")
    if return_type == "give_answer" and not final_answer:
        raise ValueError("ToolLLM give_answer requires final_answer")
    return return_type, final_answer

def _finish(request: MethodNodeRequest) -> MethodNodeResult:
    candidate = request.state.get("current_candidate")
    if not isinstance(candidate, Mapping):
        raise TypeError("ToolLLM current candidate must be a mapping")
    return_type, final_answer = _finish_input(candidate)
    frame = _top_frame(request.state)
    status = (
        ToolLLMObservationStatus.GIVE_ANSWER
        if return_type == "give_answer"
        else ToolLLMObservationStatus.GIVE_UP_AND_RESTART
    )
    observation = (
        '{"response":"successfully giving the final answer."}'
        if status is ToolLLMObservationStatus.GIVE_ANSWER
        else '{"response":"chose to give up and restart"}'
    )
    trajectory = _trace(
        _sequence(frame.get("trajectory", ()), "trajectory"),
        candidate,
        observation=observation,
        status=int(status),
    )
    explored = (*_sequence(request.state.get("explored", ()), "explored"), trajectory)

    if status is ToolLLMObservationStatus.GIVE_ANSWER:
        terminal = (*_sequence(request.state.get("terminal", ()), "terminal"), trajectory)
        return MethodNodeResult(
            value={"finish": "give_answer", "final_answer": final_answer},
            state_update={
                "explored": explored,
                "terminal": terminal,
                "finish_type": return_type,
                "final_answer": final_answer,
            },
            next_node="return",
            checkpoint=True,
            checkpoint_value={
                "query_count": request.state.get("query_count", 0),
                "finish_type": return_type,
            },
        )

    give_up = (*_sequence(request.state.get("give_up", ()), "give_up"), trajectory)
    frames = _frames(request.state)
    # Paper DFS returns prune_back_length=2 from the pruned child; the current
    # DFS frame therefore returns 1 to its caller, skipping the current frame's
    # remaining siblings while allowing the caller to continue.
    frames = frames[:-1]
    while frames and _integer(
        frames[-1].get("next_sibling", 0),
        "next_sibling",
    ) >= TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.tree_beam_size:
        frames = frames[:-1]
    return MethodNodeResult(
        value={"finish": "give_up_and_restart"},
        state_update={
            "explored": explored,
            "give_up": give_up,
            "frames": frames,
            "finish_type": return_type,
            "final_answer": "",
        },
        next_node="policy" if frames else "return",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    terminal = _sequence(request.state.get("terminal", ()), "terminal")
    give_up = _sequence(request.state.get("give_up", ()), "give_up")
    explored = _sequence(request.state.get("explored", ()), "explored")
    return MethodNodeResult(
        value={
            "task_success": bool(terminal),
            "final_answer": request.state.get("final_answer", ""),
            "finish_type": request.state.get("finish_type", ""),
            "query_count": _integer(
                request.state.get("query_count", 0),
                "query_count",
            ),
            "tool_call_count": _integer(
                request.state.get("tool_call_count", 0),
                "tool_call_count",
            ),
            "give_up_count": len(give_up),
            "terminal_count": len(terminal),
            "explored_count": len(explored),
            "budget_exhausted": request.state.get("budget_exhausted") is True,
            "selected_tool_ids": request.state.get("selected_tool_ids", ()),
            "terminal_trajectories": terminal,
        }
    )


def build_toolllm_toolbench_method_program(
    capability_ids: tuple[str, ...],
    *,
    retrieval_mode: str = "oracle",
) -> MethodProgram:
    if type(capability_ids) is not tuple or not capability_ids:
        raise ValueError("ToolLLM MethodProgram requires capability closure")
    if any(not isinstance(row, str) or not row.strip() for row in capability_ids):
        raise ValueError("ToolLLM capability closure must contain non-empty text")
    if len(set(capability_ids)) != len(capability_ids):
        raise ValueError("ToolLLM capability closure must be unique")
    if _FINISH_NAME in capability_ids:
        raise ValueError("ToolLLM Finish is method-internal, not an external capability")
    if retrieval_mode not in _RETRIEVAL_MODES:
        raise ValueError(f"unsupported ToolLLM retrieval mode: {retrieval_mode!r}")

    fidelity = TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY
    configuration: JsonObject = {
        "source_commit": fidelity.audited_commit,
        "retrieval_mode": retrieval_mode,
        "capability_ids": capability_ids,
        "retrieved_api_count": fidelity.default_retrieved_api_count,
        "retrieval_similarity": fidelity.retrieval_similarity,
        "reference_inference_method": fidelity.reference_inference_method,
        "single_chain_max_step": fidelity.single_chain_max_step,
        "tree_beam_size": fidelity.tree_beam_size,
        "max_query_count": fidelity.max_query_count,
        "answer_count": fidelity.answer_count,
        "with_filter": fidelity.with_filter,
        "final_answer_back_length": fidelity.final_answer_back_length,
        "prune_back_length": fidelity.prune_back_length,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="toolllm",
            implementation_version=fidelity.audited_commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="toolllm.toolbench.dfsdt.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )

    entrypoint = "prepare_retrieval" if retrieval_mode == "retrieved-top5" else "policy"
    builder = MethodProgramBuilder(identity, entrypoint=entrypoint)
    if retrieval_mode == "retrieved-top5":
        builder.route(
            "prepare_retrieval",
            "toolllm.api-retriever.prepare",
            _prepare_retrieval,
            ("retrieve", "policy"),
        )
        builder.capability(
            "retrieve",
            "toolllm.api-retriever.query",
            _SEMANTIC_CAPABILITY,
            ("record_retrieval",),
            effect_class=EffectClass.PURE,
            evidence_obligations=("toolllm.api-selection",),
        )
        builder.compute(
            "record_retrieval",
            "toolllm.api-retriever.materialize",
            _record_retrieval,
            ("policy",),
        )

    builder.agent(
        "policy",
        "toolllm.dfsdt.generate",
        _POLICY_AGENT_ID,
        ("record_generation",),
        view_handler=_policy_view,
        max_visits=fidelity.max_query_count,
    )
    builder.route(
        "record_generation",
        "toolllm.dfsdt.record-generation",
        _record_generation,
        ("commit_thought", "finish", "hallucination", "prepare_tool", "return"),
        max_visits=fidelity.max_query_count,
    )
    builder.route(
        "commit_thought",
        "toolllm.dfsdt.commit-thought",
        _commit_thought,
        ("policy", "return"),
        max_visits=fidelity.max_query_count,
    )
    builder.route(
        "hallucination",
        "toolllm.dfsdt.hallucinated-function",
        _hallucination,
        ("policy", "return"),
        max_visits=fidelity.max_query_count,
    )
    builder.compute(
        "prepare_tool",
        "toolllm.tool.prepare",
        _prepare_tool,
        ("invoke_tool",),
        max_visits=fidelity.max_query_count,
    )
    builder.dynamic_capability(
        "invoke_tool",
        "toolllm.tool.invoke",
        capability_ids,
        _tool_target,
        ("record_tool",),
        effect_class=EffectClass.NON_IDEMPOTENT,
        max_visits=fidelity.max_query_count,
        evidence_obligations=("toolllm.tool-effect",),
    )
    builder.route(
        "record_tool",
        "toolllm.tool.record",
        _record_tool,
        ("policy", "return"),
        max_visits=fidelity.max_query_count,
    )
    builder.route(
        "finish",
        "toolllm.finish",
        _finish,
        ("policy", "return"),
        max_visits=fidelity.max_query_count,
    )
    builder.return_node("return", "toolllm.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(
            (_SEMANTIC_CAPABILITY,)
            if retrieval_mode == "retrieved-top5"
            else ()
        ),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "toolllm.trajectory",
            "toolllm.api-selection",
            "toolllm.tool-effect",
        ),
        metric_names=(
            "task_success",
            "query_count",
            "tool_call_count",
            "give_up_count",
        ),
        artifact_kinds=("toolllm_trajectory",),
    )


__all__ = [
    "build_toolllm_toolbench_method_program",
    "toolllm_toolbench_initial_state",
]
