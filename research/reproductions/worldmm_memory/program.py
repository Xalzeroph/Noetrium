from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.machines.api import (
    ChildFailurePolicy,
    ChildResearchMachineExecution,
    ChildResearchMachineRequest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodEvent,
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import WORLDMM_REFERENCE_FIDELITY
from .memory import (
    WORLDMM_MEMORY_PROGRAM,
    WorldMMMemoryType,
    worldmm_memory_initial_data,
)
from .source import WORLDMM_INITIAL_RELEASE_COMMIT


_REASON_CAPABILITY = "worldmm.reasoning.generate"
_ANSWER_CAPABILITY = "worldmm.answer.generate"
_MEMORY_HOST_ID = "worldmm.heterogeneous-multimodal-memory"


def _text(
    value: object,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be text")
    result = value.strip()
    if not allow_empty and not result:
        raise ValueError(f"{field_name} must be non-empty text")
    return result


def _mapping(value: object, field_name: str) -> dict[str, JsonValue]:
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must be an object")
    return decoded


def _rows(value: object, field_name: str) -> tuple[JsonObject, ...]:
    decoded = thaw_json(value)
    if not isinstance(decoded, (tuple, list)):
        raise TypeError(f"{field_name} must be a sequence")
    rows: list[JsonObject] = []
    for row in decoded:
        if not isinstance(row, dict):
            raise TypeError(f"{field_name} rows must be objects")
        rows.append(row)
    return tuple(rows)


def worldmm_method_initial_state(
    *,
    question: str,
    until_time: int,
    choices: JsonObject | None = None,
) -> JsonObject:
    question = _text(question, "WorldMM question")
    if type(until_time) is not int or until_time < 1:
        raise ValueError("WorldMM until_time must be positive")
    choice_map = {} if choices is None else dict(choices)
    if any(
        type(key) is not str
        or not key.strip()
        or type(value) is not str
        or not value.strip()
        for key, value in choice_map.items()
    ):
        raise TypeError("WorldMM choices must map text labels to text")
    return {
        "source_commit": WORLDMM_INITIAL_RELEASE_COMMIT,
        "question": question,
        "choices": choice_map,
        "until_time": until_time,
        "round_count": 0,
        "error_count": 0,
        "round_history": (),
        "retrieved_items": (),
        "pending_memory_type": None,
        "pending_query": None,
        "last_reasoning_raw": None,
        "final_answer": None,
        "memory_index_digest": None,
    }


def _require_child(request: MethodNodeRequest) -> None:
    if request.child_machines is None or request.parent_machine_id is None:
        raise RuntimeError(
            "WorldMM requires journal-backed child MemoryMachine"
        )


def _memory_step(
    request: MethodNodeRequest,
    *,
    kind: str,
    payload: JsonObject,
    suffix: str,
) -> ChildResearchMachineExecution:
    _require_child(request)
    child_machine_id = f"{request.parent_machine_id}:worldmm-memory"
    child = request.child_machines.step_once(
        ChildResearchMachineRequest(
            host_id=_MEMORY_HOST_ID,
            parent_machine_id=request.parent_machine_id,
            child_machine_id=child_machine_id,
            instance_identity={
                "source_commit": WORLDMM_INITIAL_RELEASE_COMMIT,
                "program_digest": WORLDMM_MEMORY_PROGRAM.program_digest,
                "child_registry_identity_digest": (
                    request.child_machines.identity_digest
                ),
            },
            initial_data=worldmm_memory_initial_data(),
            failure_policy=ChildFailurePolicy.FAIL_PARENT,
            payload={
                "event": {
                    "kind": kind,
                    "payload": payload,
                    "source": "worldmm-method",
                }
            },
            command_id_prefix=(
                f"{child_machine_id}:{suffix}:"
                f"{request.node_id}:{request.visit}"
            ),
        )
    )
    if not isinstance(child, ChildResearchMachineExecution):
        raise TypeError(
            "WorldMM child MemoryMachine returned invalid execution"
        )
    if child.status.value != "runnable":
        raise RuntimeError(
            "WorldMM child MemoryMachine stopped unexpectedly: "
            f"{child.status.value}"
        )
    if not isinstance(child.result, Mapping):
        raise TypeError(
            "WorldMM child MemoryMachine result must be an object"
        )
    return child


def _index_memory(request: MethodNodeRequest) -> MethodNodeResult:
    until_time = request.state.get("until_time")
    if type(until_time) is not int or until_time < 1:
        raise ValueError("WorldMM state until_time is invalid")
    child = _memory_step(
        request,
        kind="worldmm.memory.index",
        payload={"until_time": until_time},
        suffix="index",
    )
    result = _mapping(child.result, "WorldMM index result")
    digests = result.get("facet_index_digests", {})
    if not isinstance(digests, Mapping):
        raise TypeError(
            "WorldMM index result facet_index_digests must be an object"
        )
    return MethodNodeResult(
        value=result,
        state_update={
            "memory_index_digest": canonical_digest(result),
        },
        next_node="reason",
        child_links=(child.link,),
        events=(
            MethodEvent(
                "worldmm.memory.indexed",
                {
                    "indexed_time": until_time,
                    "facet_index_digests": dict(digests),
                },
            ),
        ),
    )


def _full_query(state: Mapping[str, JsonValue]) -> str:
    question = _text(state.get("question"), "WorldMM question")
    choices = state.get("choices", {})
    if not isinstance(choices, Mapping):
        raise TypeError("WorldMM choices state must be an object")
    if not choices:
        return f"Query: {question}"
    choice_text = " ".join(
        f"({key}) {value}"
        for key, value in sorted(choices.items())
    )
    return f"Query: {question}\nChoices: {choice_text}"


def _history_text(state: Mapping[str, JsonValue]) -> str:
    rows = _rows(
        state.get("round_history", ()),
        "WorldMM round_history",
    )
    if not rows:
        return "[]"
    blocks = []
    for row in rows:
        blocks.append(
            "### Round {round_num}\n"
            "Decision: search\n"
            "Memory: {memory_type}\n"
            "Search Query: {search_query}\n"
            "Retrieved:\n{retrieved_content}".format(
                round_num=row.get("round_num"),
                memory_type=row.get("memory_type"),
                search_query=row.get("search_query"),
                retrieved_content=row.get(
                    "retrieved_content",
                    "[No results]",
                ),
            )
        )
    return "\n\n".join(blocks)


def _invoke_raw(
    request: MethodNodeRequest,
    capability_id: str,
    payload: JsonObject,
) -> str:
    if request.capabilities is None:
        raise RuntimeError(
            f"WorldMM requires capability binding: {capability_id}"
        )
    result = request.capabilities.invoke(
        CapabilityRequest(
            capability_id=capability_id,
            payload=payload,
            context=request.context,
        )
    )
    if not isinstance(result, CapabilityResult):
        raise TypeError(
            f"WorldMM capability returned invalid result: {capability_id}"
        )
    decoded = thaw_json(result.payload)
    if isinstance(decoded, str):
        return decoded
    if isinstance(decoded, dict):
        for key in ("raw_response", "text", "answer"):
            value = decoded.get(key)
            if isinstance(value, str):
                return value
    raise TypeError(
        f"WorldMM capability {capability_id} must return text"
    )


def _parse_reasoning_response(raw: str) -> JsonObject:
    try:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(match.group() if match else raw)
        if not isinstance(data, dict):
            raise TypeError("reasoning response must decode to object")
        decision = str(data.get("decision", "answer")).lower()
        selected = None
        if decision == "search" and "selected_memory" in data:
            value = data["selected_memory"]
            if isinstance(value, Mapping):
                selected = {
                    "memory_type": str(
                        value.get("memory_type", "")
                    ).lower(),
                    "search_query": str(
                        value.get("search_query", "")
                    ),
                }
        return {
            "decision": decision,
            "selected_memory": selected,
            "parse_fallback": False,
        }
    except (json.JSONDecodeError, TypeError, AttributeError):
        # Official WorldMM defaults malformed reasoning JSON to answer.
        return {
            "decision": "answer",
            "selected_memory": None,
            "parse_fallback": True,
        }


def _limits_exhausted(
    *,
    rounds: int,
    errors: int,
) -> bool:
    f = WORLDMM_REFERENCE_FIDELITY
    return (
        rounds >= f.max_retrieval_rounds
        or errors >= f.max_reasoning_errors
    )


def _reason(request: MethodNodeRequest) -> MethodNodeResult:
    rounds = request.state.get("round_count", 0)
    errors = request.state.get("error_count", 0)
    if type(rounds) is not int or rounds < 0:
        raise ValueError("WorldMM round_count state is invalid")
    if type(errors) is not int or errors < 0:
        raise ValueError("WorldMM error_count state is invalid")
    if _limits_exhausted(rounds=rounds, errors=errors):
        return MethodNodeResult(
            value={"forced_answer": True},
            next_node="answer",
        )

    next_round = rounds + 1
    payload = {
        "query": _full_query(request.state),
        "round_history": _history_text(request.state),
        "round_num": next_round,
        "allowed_memory_types": (
            WORLDMM_REFERENCE_FIDELITY.memory_types
        ),
        "instruction": (
            'Decide "search" or "answer". If searching, select '
            "exactly one memory type and form a search query."
        ),
    }
    try:
        raw = _invoke_raw(
            request,
            _REASON_CAPABILITY,
            payload,
        )
    except Exception as exc:
        next_errors = errors + 1
        exhausted = _limits_exhausted(
            rounds=next_round,
            errors=next_errors,
        )
        return MethodNodeResult(
            value={
                "round_num": next_round,
                "reasoning_error": type(exc).__name__,
            },
            state_update={
                "round_count": next_round,
                "error_count": next_errors,
            },
            next_node="answer" if exhausted else "reason",
            events=(
                MethodEvent(
                    "worldmm.reasoning.error",
                    {
                        "round_num": next_round,
                        "error_count": next_errors,
                        "error_type": type(exc).__name__,
                    },
                ),
            ),
        )

    parsed = _parse_reasoning_response(raw)
    decision = parsed["decision"]
    update: JsonObject = {
        "round_count": next_round,
        "last_reasoning_raw": raw,
    }
    if decision == "answer":
        return MethodNodeResult(
            value=parsed,
            state_update=update,
            next_node="answer",
            events=(
                MethodEvent(
                    "worldmm.reasoning.answer",
                    {
                        "round_num": next_round,
                        "parse_fallback": parsed["parse_fallback"],
                    },
                ),
            ),
        )

    if decision != "search":
        return MethodNodeResult(
            value=parsed,
            state_update=update,
            next_node=(
                "answer"
                if _limits_exhausted(
                    rounds=next_round,
                    errors=errors,
                )
                else "reason"
            ),
        )

    selected = parsed.get("selected_memory")
    if not isinstance(selected, Mapping):
        next_errors = errors + 1
        update["error_count"] = next_errors
        return MethodNodeResult(
            value=parsed,
            state_update=update,
            next_node=(
                "answer"
                if _limits_exhausted(
                    rounds=next_round,
                    errors=next_errors,
                )
                else "reason"
            ),
            events=(
                MethodEvent(
                    "worldmm.reasoning.invalid-search",
                    {
                        "round_num": next_round,
                        "reason": "missing-selected-memory",
                    },
                ),
            ),
        )

    memory_name = str(selected.get("memory_type", "")).lower()
    query = str(selected.get("search_query", ""))
    if memory_name not in WORLDMM_REFERENCE_FIDELITY.memory_types:
        next_errors = errors + 1
        update["error_count"] = next_errors
        return MethodNodeResult(
            value=parsed,
            state_update=update,
            next_node=(
                "answer"
                if _limits_exhausted(
                    rounds=next_round,
                    errors=next_errors,
                )
                else "reason"
            ),
            events=(
                MethodEvent(
                    "worldmm.reasoning.invalid-search",
                    {
                        "round_num": next_round,
                        "reason": "unknown-memory-type",
                        "memory_type": memory_name,
                    },
                ),
            ),
        )

    update.update({
        "pending_memory_type": memory_name,
        "pending_query": query,
    })
    return MethodNodeResult(
        value=parsed,
        state_update=update,
        next_node="retrieve",
        events=(
            MethodEvent(
                "worldmm.reasoning.search",
                {
                    "round_num": next_round,
                    "memory_type": memory_name,
                    "search_query": query,
                },
            ),
        ),
    )


def _retrieved_content(
    memory_type: WorldMMMemoryType,
    items: tuple[JsonObject, ...],
) -> str:
    if memory_type is WorldMMMemoryType.VISUAL:
        frame_count = sum(
            len(tuple(item.get("artifact_refs", ())))
            for item in items
        )
        return (
            f"[{frame_count} images from {len(items)} clips]"
            if items
            else "[No results]"
        )
    text = "\n\n".join(
        str(item.get("display_text", ""))
        for item in items
        if str(item.get("display_text", ""))
    )
    return text or "[No results]"


def _retrieve(request: MethodNodeRequest) -> MethodNodeResult:
    memory_type = WorldMMMemoryType(
        _text(
            request.state.get("pending_memory_type"),
            "WorldMM pending memory type",
        )
    )
    query = request.state.get("pending_query")
    if type(query) is not str:
        raise TypeError("WorldMM pending query must be text")

    child = _memory_step(
        request,
        kind="worldmm.memory.retrieve",
        payload={
            "memory_type": memory_type.value,
            "query": query,
        },
        suffix=f"retrieve-{memory_type.value}",
    )
    result = _mapping(child.result, "WorldMM retrieval result")
    raw_items = result.get("items", ())
    if isinstance(raw_items, (str, bytes, bytearray)) or not isinstance(
        raw_items,
        Sequence,
    ):
        raise TypeError("WorldMM retrieval items must be a sequence")
    items = tuple(
        _mapping(item, "WorldMM retrieved item")
        for item in raw_items
    )
    history = list(
        _rows(
            request.state.get("round_history", ()),
            "WorldMM round_history",
        )
    )
    round_num = request.state.get("round_count")
    if type(round_num) is not int or round_num < 1:
        raise ValueError("WorldMM round_count is invalid")
    history.append({
        "round_num": round_num,
        "decision": "search",
        "memory_type": memory_type.value,
        "search_query": query,
        "retrieved_content": _retrieved_content(
            memory_type,
            items,
        ),
        "retrieval_digest": result.get("retrieval_digest"),
    })
    evidence = list(
        _rows(
            request.state.get("retrieved_items", ()),
            "WorldMM retrieved_items",
        )
    )
    evidence.extend(items)

    errors = request.state.get("error_count", 0)
    if type(errors) is not int or errors < 0:
        raise ValueError("WorldMM error_count is invalid")
    exhausted = _limits_exhausted(
        rounds=round_num,
        errors=errors,
    )
    return MethodNodeResult(
        value=result,
        state_update={
            "round_history": tuple(history),
            "retrieved_items": tuple(evidence),
            "pending_memory_type": None,
            "pending_query": None,
        },
        next_node="answer" if exhausted else "reason",
        child_links=(child.link,),
        events=(
            MethodEvent(
                "worldmm.memory.evidence-recorded",
                {
                    "round_num": round_num,
                    "memory_type": memory_type.value,
                    "retrieval_digest": result.get(
                        "retrieval_digest"
                    ),
                    "item_count": len(items),
                },
            ),
        ),
    )


def _answer(request: MethodNodeRequest) -> MethodNodeResult:
    items = _rows(
        request.state.get("retrieved_items", ()),
        "WorldMM retrieved_items",
    )
    choices = request.state.get("choices", {})
    if not isinstance(choices, Mapping):
        raise TypeError("WorldMM choices state must be object")
    payload = {
        "query": _full_query(request.state),
        "retrieved_items": items,
        "multiple_choice": bool(choices),
        "instruction": (
            "Provide only the final answer from the choices."
            if choices
            else "Answer using the accumulated multimodal evidence."
        ),
    }
    try:
        answer = _invoke_raw(
            request,
            _ANSWER_CAPABILITY,
            payload,
        )
    except Exception:
        answer = "Unable to generate answer"
    return MethodNodeResult(
        value={"answer": answer},
        state_update={"final_answer": answer},
        next_node="return",
        events=(
            MethodEvent(
                "worldmm.answer.generated",
                {
                    "answer_digest": canonical_digest(answer),
                    "round_count": request.state.get(
                        "round_count",
                        0,
                    ),
                    "retrieved_item_count": len(items),
                },
            ),
        ),
    )


def _return(request: MethodNodeRequest) -> MethodNodeResult:
    answer = request.state.get("final_answer")
    if type(answer) is not str:
        raise RuntimeError("WorldMM final answer is missing")
    return MethodNodeResult(
        value={
            "source_commit": WORLDMM_INITIAL_RELEASE_COMMIT,
            "memory_program_digest": (
                WORLDMM_MEMORY_PROGRAM.program_digest
            ),
            "answer": answer,
            "round_count": request.state.get("round_count", 0),
            "error_count": request.state.get("error_count", 0),
            "round_history": request.state.get(
                "round_history",
                (),
            ),
            "retrieved_items": request.state.get(
                "retrieved_items",
                (),
            ),
            "memory_index_digest": request.state.get(
                "memory_index_digest"
            ),
        }
    )


def build_worldmm_method_program() -> MethodProgram:
    f = WORLDMM_REFERENCE_FIDELITY
    configuration: JsonObject = {
        "source_commit": WORLDMM_INITIAL_RELEASE_COMMIT,
        "memory_program_digest": WORLDMM_MEMORY_PROGRAM.program_digest,
        "memory_types": f.memory_types,
        "max_retrieval_rounds": f.max_retrieval_rounds,
        "max_reasoning_errors": f.max_reasoning_errors,
        "reason_capability": _REASON_CAPABILITY,
        "answer_capability": _ANSWER_CAPABILITY,
        "malformed_reasoning_json": "default-to-answer",
        "answer_generation_failure": "Unable to generate answer",
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="worldmm-dynamic-multimodal-memory-agent",
            implementation_version=(
                WORLDMM_INITIAL_RELEASE_COMMIT[:12]
            ),
            abi_version="noetrium.method-machine.v1",
            schema_version="worldmm.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(
        identity,
        entrypoint="index_memory",
    )
    builder.compute(
        "index_memory",
        "worldmm.memory.index",
        _index_memory,
        ("reason",),
        evidence_obligations=(
            "worldmm.memory.index-child-cut",
        ),
    )
    builder.compute(
        "reason",
        "worldmm.reasoning.step",
        _reason,
        ("reason", "retrieve", "answer"),
        max_visits=f.max_retrieval_rounds,
    )
    builder.compute(
        "retrieve",
        "worldmm.memory.retrieve",
        _retrieve,
        ("reason", "answer"),
        max_visits=f.max_retrieval_rounds,
        evidence_obligations=(
            "worldmm.memory.retrieval-child-cuts",
        ),
    )
    builder.compute(
        "answer",
        "worldmm.answer",
        _answer,
        ("return",),
    )
    builder.return_node(
        "return",
        "worldmm.result",
        _return,
    )
    return builder.build(
        configuration=configuration,
        required_capabilities=(
            _REASON_CAPABILITY,
            _ANSWER_CAPABILITY,
        ),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "worldmm.memory.index-child-cut",
            "worldmm.memory.retrieval-child-cuts",
            "worldmm.round-history",
            "worldmm.multimodal-evidence",
        ),
        metric_names=(
            "round_count",
            "error_count",
            "retrieved_item_count",
        ),
        artifact_kinds=(
            "worldmm_visual_evidence",
            "worldmm_memory_receipt",
        ),
    )


WORLDMM_METHOD_PROGRAM = build_worldmm_method_program()


__all__ = [
    "WORLDMM_METHOD_PROGRAM",
    "build_worldmm_method_program",
    "worldmm_method_initial_state",
]
