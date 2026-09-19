from __future__ import annotations

from collections.abc import Mapping, Sequence

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
)
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import MEMGPT_CLASSIC_FIDELITY
from .semantics import (
    MemGPTCoreMemory,
    MemGPTMemoryQuery,
    MemGPTMemoryTier,
    classic_summary_partition,
)

_MAIN_AGENT_ID = "memgpt.classic.agent"
_SUMMARIZER_AGENT_ID = "memgpt.classic.summarizer"

_RECALL_QUERY_CAPABILITY = "memory.recall.query"
_ARCHIVAL_QUERY_CAPABILITY = "memory.archival.query"
_ARCHIVAL_INSERT_CAPABILITY = "memory.archival.insert"

_MAX_METHOD_TURNS = 128
_MAX_SUMMARIES = 32
_MAX_MEMORY_OPERATIONS = 256

_OPERATION_KINDS = frozenset(
    {
        "core_replace",
        "core_append",
        "recall_query",
        "archival_query",
        "archival_insert",
        "context_overflow",
        "final",
    }
)


def _messages(value: object) -> tuple[JsonObject, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError("MemGPT messages must be a sequence")
    rows: list[JsonObject] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise TypeError("MemGPT messages must contain mappings")
        role = row.get("role")
        content = row.get("content")
        if not isinstance(role, str) or not role.strip():
            raise ValueError("MemGPT message role must be non-empty")
        if not isinstance(content, str):
            raise TypeError("MemGPT message content must be text")
        rows.append(freeze_json(dict(row)))
    if not rows or rows[0].get("role") != "system":
        raise ValueError("MemGPT messages must begin with the preserved system message")
    return tuple(rows)


def _core_memory(state: Mapping[str, JsonValue]) -> MemGPTCoreMemory:
    value = state.get("core_memory")
    if not isinstance(value, Mapping):
        raise TypeError("MemGPT state requires core_memory mapping")
    return MemGPTCoreMemory(value)


def _count(state: Mapping[str, JsonValue], name: str) -> int:
    value = state.get(name, 0)
    if type(value) is not int or value < 0:
        raise ValueError(f"MemGPT state {name} must be a non-negative integer")
    return value


def _operation(value: JsonValue) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError("MemGPT agent result must be an operation mapping")
    kind = value.get("kind")
    if not isinstance(kind, str) or kind not in _OPERATION_KINDS:
        raise ValueError(f"unsupported MemGPT operation kind: {kind!r}")
    return value


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"MemGPT {field} must be text")
    return value


def _memgpt_agent_view(request: MethodNodeRequest) -> JsonObject:
    """Expose only the classic model-visible memory/context projection."""

    return {
        "core_memory": _core_memory(request.state).blocks,
        "messages": _messages(request.state.get("messages")),
        "turn": _count(request.state, "turn"),
        "memory_query_count": _count(request.state, "memory_query_count"),
        "memory_write_count": _count(request.state, "memory_write_count"),
        "summary_count": _count(request.state, "summary_count"),
    }


def _memgpt_summary_view(request: MethodNodeRequest) -> JsonObject:
    if not isinstance(request.previous_value, Mapping):
        raise TypeError("MemGPT summary node requires a prepared summary projection")
    messages = request.previous_value.get("messages_to_summarize")
    cutoff = request.previous_value.get("cutoff")
    if not isinstance(messages, tuple):
        raise TypeError("MemGPT summary projection messages must be a tuple")
    if type(cutoff) is not int or cutoff < 1:
        raise ValueError("MemGPT summary projection cutoff must be positive")
    return {
        "messages_to_summarize": messages,
        "cutoff": cutoff,
    }


def memgpt_classic_initial_state(
    *,
    core_memory: Mapping[str, str],
    messages: Sequence[Mapping[str, JsonValue]],
) -> JsonObject:
    """Create immutable initial method state for the classic memory loop."""

    core = MemGPTCoreMemory(core_memory)
    history = _messages(messages)
    return {
        "core_memory": core.blocks,
        "messages": history,
        "turn": 0,
        "memory_query_count": 0,
        "memory_write_count": 0,
        "summary_count": 0,
        "pending_memory_tier": "",
        "pending_memory_query": "",
        "summary_retain": (),
        "summary_cutoff": 0,
        "final_response": "",
    }


def _route_operation(request: MethodNodeRequest) -> MethodNodeResult:
    operation = _operation(request.previous_value)
    kind = _text(operation.get("kind"), "operation kind")
    mapping = {
        "core_replace": "core_replace",
        "core_append": "core_append",
        "recall_query": "prepare_recall",
        "archival_query": "prepare_archival_query",
        "archival_insert": "prepare_archival_insert",
        "context_overflow": "prepare_summary",
        "final": "return",
    }
    return MethodNodeResult(
        value=operation,
        next_node=mapping[kind],
    )


def _record_main_turn(
    state: Mapping[str, JsonValue],
    *,
    operation: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    turn = _count(state, "turn") + 1
    return {"turn": turn}


def _core_replace(request: MethodNodeRequest) -> MethodNodeResult:
    operation = _operation(request.previous_value)
    label = _text(operation.get("label"), "core_replace label")
    old = _text(operation.get("old"), "core_replace old", allow_empty=True)
    new = _text(operation.get("new"), "core_replace new", allow_empty=True)
    updated = _core_memory(request.state).replace(label, old, new)
    return MethodNodeResult(
        value={"kind": "core_replace", "label": label},
        state_update={
            "core_memory": updated.blocks,
            "memory_write_count": _count(request.state, "memory_write_count") + 1,
            **_record_main_turn(request.state, operation=operation),
        },
        checkpoint=True,
        checkpoint_value={"memory_write": "core_replace", "label": label},
    )


def _core_append(request: MethodNodeRequest) -> MethodNodeResult:
    operation = _operation(request.previous_value)
    label = _text(operation.get("label"), "core_append label")
    content = _text(operation.get("content"), "core_append content", allow_empty=True)
    updated = _core_memory(request.state).append(label, content)
    return MethodNodeResult(
        value={"kind": "core_append", "label": label},
        state_update={
            "core_memory": updated.blocks,
            "memory_write_count": _count(request.state, "memory_write_count") + 1,
            **_record_main_turn(request.state, operation=operation),
        },
        checkpoint=True,
        checkpoint_value={"memory_write": "core_append", "label": label},
    )


def _memory_query(
    operation: Mapping[str, JsonValue],
    tier: MemGPTMemoryTier,
) -> MemGPTMemoryQuery:
    query = _text(operation.get("query"), f"{tier.value} query")
    page = operation.get("page", 0)
    count = operation.get(
        "count",
        MEMGPT_CLASSIC_FIDELITY.recall_default_page_size
        if tier is MemGPTMemoryTier.RECALL
        else MEMGPT_CLASSIC_FIDELITY.archival_default_page_size,
    )
    if type(page) is not int or type(count) is not int:
        raise TypeError("MemGPT memory page/count must be integers")
    return MemGPTMemoryQuery(tier, query, page=page, count=count)


def _prepare_query(
    request: MethodNodeRequest,
    tier: MemGPTMemoryTier,
) -> MethodNodeResult:
    operation = _operation(request.previous_value)
    query = _memory_query(operation, tier)
    return MethodNodeResult(
        value={
            "tier": query.tier.value,
            "query": query.query,
            "page": query.page,
            "count": query.count,
            "start": query.start,
        },
        state_update={
            "pending_memory_tier": query.tier.value,
            "pending_memory_query": query.query,
            **_record_main_turn(request.state, operation=operation),
        },
    )


def _prepare_recall(request: MethodNodeRequest) -> MethodNodeResult:
    return _prepare_query(request, MemGPTMemoryTier.RECALL)


def _prepare_archival_query(request: MethodNodeRequest) -> MethodNodeResult:
    return _prepare_query(request, MemGPTMemoryTier.ARCHIVAL)


def _append_memory_observation(
    state: Mapping[str, JsonValue],
    payload: JsonValue,
) -> tuple[JsonObject, ...]:
    history = _messages(state.get("messages"))
    tier = _text(state.get("pending_memory_tier"), "pending memory tier")
    query = _text(state.get("pending_memory_query"), "pending memory query")
    observation = freeze_json(
        {
            "role": "memory",
            "content": str(payload),
            "tier": tier,
            "query": query,
        }
    )
    return (*history, observation)


def _record_query_result(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value=request.previous_value,
        state_update={
            "messages": _append_memory_observation(
                request.state,
                request.previous_value,
            ),
            "memory_query_count": _count(request.state, "memory_query_count") + 1,
            "pending_memory_tier": "",
            "pending_memory_query": "",
        },
        checkpoint=True,
        checkpoint_value={
            "memory_query_count": _count(request.state, "memory_query_count") + 1,
        },
    )


def _prepare_archival_insert(request: MethodNodeRequest) -> MethodNodeResult:
    operation = _operation(request.previous_value)
    content = _text(operation.get("content"), "archival insert content")
    return MethodNodeResult(
        value={"tier": "archival", "content": content},
        state_update={
            **_record_main_turn(request.state, operation=operation),
        },
    )


def _record_archival_insert(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value=request.previous_value,
        state_update={
            "memory_write_count": _count(request.state, "memory_write_count") + 1,
        },
        checkpoint=True,
        checkpoint_value={
            "memory_write_count": _count(request.state, "memory_write_count") + 1,
        },
    )


def _prepare_summary(request: MethodNodeRequest) -> MethodNodeResult:
    _operation(request.previous_value)
    history = _messages(request.state.get("messages"))
    partition = classic_summary_partition(history)
    return MethodNodeResult(
        value={
            "messages_to_summarize": partition.summarize,
            "cutoff": partition.cutoff,
        },
        state_update={
            "summary_retain": partition.retain,
            "summary_cutoff": partition.cutoff,
        },
    )


def _apply_summary(request: MethodNodeRequest) -> MethodNodeResult:
    if not isinstance(request.previous_value, Mapping):
        raise TypeError("MemGPT summarizer result must be a mapping")
    summary = _text(request.previous_value.get("summary"), "summary")
    history = _messages(request.state.get("messages"))
    retained = request.state.get("summary_retain")
    if not isinstance(retained, tuple) or any(
        not isinstance(row, Mapping) for row in retained
    ):
        raise TypeError("MemGPT summary retain state is malformed")
    summary_row: JsonObject = {
        "role": "system",
        "content": summary,
        "kind": "conversation_summary",
    }
    rebuilt = (
        history[0],
        summary_row,
        *(freeze_json(dict(row)) for row in retained),
    )
    return MethodNodeResult(
        value={"summary_applied": True},
        state_update={
            "messages": rebuilt,
            "summary_count": _count(request.state, "summary_count") + 1,
            "summary_retain": (),
            "summary_cutoff": 0,
        },
        checkpoint=True,
        checkpoint_value={
            "summary_count": _count(request.state, "summary_count") + 1,
            "retry_same_turn": _count(request.state, "turn"),
        },
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    operation = _operation(request.previous_value)
    content = _text(operation.get("content"), "final response", allow_empty=True)
    return MethodNodeResult(
        value={
            "response": content,
            "turns": _count(request.state, "turn") + 1,
            "memory_query_count": _count(request.state, "memory_query_count"),
            "memory_write_count": _count(request.state, "memory_write_count"),
            "summary_count": _count(request.state, "summary_count"),
            "core_memory": _core_memory(request.state).blocks,
        },
        state_update={
            "final_response": content,
            "turn": _count(request.state, "turn") + 1,
        },
    )


def build_memgpt_classic_method_program() -> MethodProgram:
    configuration: JsonObject = {
        "paper_era_anchor": MEMGPT_CLASSIC_FIDELITY.audited_anchor_commit,
        "overflow_fix": MEMGPT_CLASSIC_FIDELITY.context_overflow_fix_commit,
        "core_memory_in_context": True,
        "recall_memory_external": True,
        "archival_memory_external": True,
        "recall_default_page_size": MEMGPT_CLASSIC_FIDELITY.recall_default_page_size,
        "archival_default_page_size": MEMGPT_CLASSIC_FIDELITY.archival_default_page_size,
        "overflow_strategy": MEMGPT_CLASSIC_FIDELITY.overflow_strategy,
        "summary_fraction": MEMGPT_CLASSIC_FIDELITY.default_summary_fraction,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="memgpt-classic",
            implementation_version=MEMGPT_CLASSIC_FIDELITY.audited_anchor_commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="memgpt-classic.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="agent")
    builder.agent(
        "agent",
        "memgpt.agent",
        _MAIN_AGENT_ID,
        ("route",),
        view_handler=_memgpt_agent_view,
        max_visits=_MAX_METHOD_TURNS + _MAX_SUMMARIES,
    )
    builder.route(
        "route",
        "memgpt.operation.route",
        _route_operation,
        (
            "core_replace",
            "core_append",
            "prepare_recall",
            "prepare_archival_query",
            "prepare_archival_insert",
            "prepare_summary",
            "return",
        ),
        max_visits=_MAX_METHOD_TURNS + _MAX_SUMMARIES,
    )
    builder.compute(
        "core_replace",
        "memgpt.core.replace",
        _core_replace,
        ("agent",),
        max_visits=_MAX_MEMORY_OPERATIONS,
    )
    builder.compute(
        "core_append",
        "memgpt.core.append",
        _core_append,
        ("agent",),
        max_visits=_MAX_MEMORY_OPERATIONS,
    )
    builder.compute(
        "prepare_recall",
        "memgpt.recall.prepare",
        _prepare_recall,
        ("recall_query",),
        max_visits=_MAX_MEMORY_OPERATIONS,
    )
    builder.capability(
        "recall_query",
        "memgpt.recall.query",
        _RECALL_QUERY_CAPABILITY,
        ("record_query",),
        effect_class=EffectClass.PURE,
        max_visits=_MAX_MEMORY_OPERATIONS,
    )
    builder.compute(
        "prepare_archival_query",
        "memgpt.archival.query.prepare",
        _prepare_archival_query,
        ("archival_query",),
        max_visits=_MAX_MEMORY_OPERATIONS,
    )
    builder.capability(
        "archival_query",
        "memgpt.archival.query",
        _ARCHIVAL_QUERY_CAPABILITY,
        ("record_query",),
        effect_class=EffectClass.PURE,
        max_visits=_MAX_MEMORY_OPERATIONS,
    )
    builder.compute(
        "record_query",
        "memgpt.memory.query.record",
        _record_query_result,
        ("agent",),
        max_visits=_MAX_MEMORY_OPERATIONS,
    )
    builder.compute(
        "prepare_archival_insert",
        "memgpt.archival.insert.prepare",
        _prepare_archival_insert,
        ("archival_insert",),
        max_visits=_MAX_MEMORY_OPERATIONS,
    )
    builder.capability(
        "archival_insert",
        "memgpt.archival.insert",
        _ARCHIVAL_INSERT_CAPABILITY,
        ("record_archival_insert",),
        effect_class=EffectClass.RECONCILABLE,
        max_visits=_MAX_MEMORY_OPERATIONS,
        evidence_obligations=("memory.archival.effect",),
    )
    builder.compute(
        "record_archival_insert",
        "memgpt.archival.insert.record",
        _record_archival_insert,
        ("agent",),
        max_visits=_MAX_MEMORY_OPERATIONS,
    )
    builder.compute(
        "prepare_summary",
        "memgpt.context.summary.prepare",
        _prepare_summary,
        ("summarizer",),
        max_visits=_MAX_SUMMARIES,
    )
    builder.agent(
        "summarizer",
        "memgpt.context.summarize",
        _SUMMARIZER_AGENT_ID,
        ("apply_summary",),
        view_handler=_memgpt_summary_view,
        max_visits=_MAX_SUMMARIES,
    )
    builder.compute(
        "apply_summary",
        "memgpt.context.summary.apply",
        _apply_summary,
        ("agent",),
        max_visits=_MAX_SUMMARIES,
    )
    builder.return_node("return", "memgpt.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(
            _RECALL_QUERY_CAPABILITY,
            _ARCHIVAL_QUERY_CAPABILITY,
            _ARCHIVAL_INSERT_CAPABILITY,
        ),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "memgpt.memory.operations",
            "memgpt.context.projection",
            "memory.archival.effect",
        ),
        metric_names=(
            "task_success",
            "agent_turn_count",
            "memory_query_count",
            "memory_write_count",
            "summary_count",
        ),
        artifact_kinds=("memgpt_trajectory", "memgpt_memory_trace"),
    )


MEMGPT_CLASSIC_METHOD_PROGRAM = build_memgpt_classic_method_program()


__all__ = [
    "MEMGPT_CLASSIC_METHOD_PROGRAM",
    "build_memgpt_classic_method_program",
    "memgpt_classic_initial_state",
]
