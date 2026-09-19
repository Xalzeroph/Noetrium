from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    MachineJournalPort,
    MachineSnapshotStorePort,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.machines import (
    MemoryConcern,
    MemoryProgramBuilder,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgram,
    ResearchProgramHost,
)

from .fidelity import PROVIDELLM_REFERENCE_FIDELITY
from .source import PROVIDELLM_PAPER_ERA_COMMIT


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _sequence(value: object, field_name: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(value)


def providellm_memory_initial_data(
    *,
    short_capacity: int,
    long_capacity: int,
    duplicate_horizon: int,
) -> JsonObject:
    for name, value in (
        ("short_capacity", short_capacity),
        ("long_capacity", long_capacity),
        ("duplicate_horizon", duplicate_horizon),
    ):
        if type(value) is not int or value < 1:
            raise ValueError(f"ProVideLLM {name} must be positive")
    if duplicate_horizon >= short_capacity:
        raise ValueError(
            "ProVideLLM duplicate_horizon must be smaller than short_capacity"
        )
    return {
        "source_commit": PROVIDELLM_PAPER_ERA_COMMIT,
        "short_capacity": short_capacity,
        "long_capacity": long_capacity,
        "duplicate_horizon": duplicate_horizon,
        "tokens": (),
        "prediction_history": (),
        "frame_count": 0,
        "short_eviction_count": 0,
        "long_eviction_count": 0,
        "verbalized_insert_count": 0,
        "last_result": None,
    }


def _event(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.payload)
    if not isinstance(decoded, dict):
        raise TypeError("ProVideLLM memory payload must be an object")
    event = decoded.get("event")
    if not isinstance(event, Mapping):
        raise TypeError("ProVideLLM memory requires event envelope")
    value = thaw_json(event)
    if not isinstance(value, dict):
        raise TypeError("ProVideLLM event must decode to an object")
    return value


def _data(request: ProgramNodeRequest) -> dict[str, object]:
    value = thaw_json(request.data)
    if not isinstance(value, dict):
        raise TypeError("ProVideLLM memory data must be an object")
    if value.get("source_commit") != PROVIDELLM_PAPER_ERA_COMMIT:
        raise ValueError("ProVideLLM source identity drifted")
    return value


def _capacity(data: Mapping[str, object], name: str) -> int:
    value = data.get(name)
    if type(value) is not int or value < 1:
        raise ValueError(f"ProVideLLM state {name} is invalid")
    return value


def _cache_rows(data: Mapping[str, object]) -> list[dict[str, object]]:
    rows = _sequence(data.get("tokens", ()), "ProVideLLM tokens")
    decoded: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("ProVideLLM cache rows must be objects")
        value = thaw_json(row)
        if not isinstance(value, dict):
            raise TypeError("ProVideLLM cache row must decode to object")
        kind = value.get("kind")
        if kind not in {"visual", "long_text"}:
            raise ValueError("ProVideLLM cache token kind is invalid")
        decoded.append(value)
    return decoded


def _predictions(data: Mapping[str, object]) -> list[str]:
    return [
        _text(row, "ProVideLLM prediction")
        for row in _sequence(
            data.get("prediction_history", ()),
            "ProVideLLM prediction_history",
        )
    ]


def _remove_first_kind(
    rows: list[dict[str, object]],
    kind: str,
) -> dict[str, object] | None:
    for index, row in enumerate(rows):
        if row.get("kind") == kind:
            return rows.pop(index)
    return None


def _count_kind(rows: Sequence[Mapping[str, object]], kind: str) -> int:
    return sum(1 for row in rows if row.get("kind") == kind)


def _frame(
    request: ProgramNodeRequest,
    data: Mapping[str, object],
    payload: Mapping[str, object],
) -> ProgramNodeResult:
    visual_token_ref = _text(
        payload.get("visual_token_ref"),
        "ProVideLLM visual_token_ref",
    )
    prediction_text = _text(
        payload.get("prediction_text"),
        "ProVideLLM prediction_text",
    )
    short_capacity = _capacity(data, "short_capacity")
    long_capacity = _capacity(data, "long_capacity")
    duplicate_horizon = _capacity(data, "duplicate_horizon")
    frame_count = data.get("frame_count", 0)
    if type(frame_count) is not int or frame_count < 0:
        raise ValueError("ProVideLLM frame_count state is invalid")

    tokens = _cache_rows(data)
    predictions = _predictions(data)
    tokens.append({
        "kind": "visual",
        "visual_token_ref": visual_token_ref,
        "frame_index": frame_count,
    })
    predictions.append(prediction_text)

    evicted_visual = None
    verbalized_text = None
    evicted_long = None

    if _count_kind(tokens, "visual") > short_capacity:
        evicted_visual = _remove_first_kind(tokens, "visual")
        candidate = predictions[-short_capacity]
        recent = tuple(predictions[-duplicate_horizon:])
        if candidate not in recent:
            verbalized_text = candidate
            tokens.append({
                "kind": "long_text",
                "marker": PROVIDELLM_REFERENCE_FIDELITY.long_term_marker,
                "text": candidate,
                "inserted_at_frame": frame_count,
            })
            if _count_kind(tokens, "long_text") > long_capacity:
                evicted_long = _remove_first_kind(tokens, "long_text")

    short_evictions = data.get("short_eviction_count", 0)
    long_evictions = data.get("long_eviction_count", 0)
    verbalized_inserts = data.get("verbalized_insert_count", 0)
    if any(
        type(value) is not int or value < 0
        for value in (short_evictions, long_evictions, verbalized_inserts)
    ):
        raise ValueError("ProVideLLM cache counters are invalid")

    next_short_evictions = short_evictions + (1 if evicted_visual else 0)
    next_long_evictions = long_evictions + (1 if evicted_long else 0)
    next_verbalized = verbalized_inserts + (1 if verbalized_text else 0)
    next_frame_count = frame_count + 1

    value = {
        "frame_index": frame_count,
        "visual_token_ref": visual_token_ref,
        "prediction_text": prediction_text,
        "evicted_visual_token": evicted_visual,
        "verbalized_text": verbalized_text,
        "evicted_long_token": evicted_long,
        "short_token_count": _count_kind(tokens, "visual"),
        "long_token_count": _count_kind(tokens, "long_text"),
        "cache_token_count": len(tokens),
    }
    return ProgramNodeResult(
        value=value,
        state_update={
            "tokens": tuple(tokens),
            "prediction_history": tuple(predictions),
            "frame_count": next_frame_count,
            "short_eviction_count": next_short_evictions,
            "long_eviction_count": next_long_evictions,
            "verbalized_insert_count": next_verbalized,
            "last_result": value,
        },
        events=({
            "type": "providellm_interleaved_cache_step",
            "frame_index": frame_count,
            "short_token_count": value["short_token_count"],
            "long_token_count": value["long_token_count"],
            "verbalized": verbalized_text is not None,
        },),
    )


def _dispatch(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if binding is not None:
        raise TypeError("ProVideLLM paper cache semantics require no provider binding")
    data = _data(request)
    event = _event(request)
    kind = _text(event.get("kind"), "ProVideLLM memory event kind")
    payload = event.get("payload", {})
    if not isinstance(payload, Mapping):
        raise TypeError("ProVideLLM event payload must be an object")
    payload = thaw_json(payload)
    if not isinstance(payload, dict):
        raise TypeError("ProVideLLM event payload must decode to object")

    if kind == "providellm.memory.frame":
        return _frame(request, data, payload)

    if kind == "providellm.memory.readout":
        tokens = _cache_rows(data)
        value = {
            "frame_count": data.get("frame_count", 0),
            "tokens": tuple(tokens),
            "short_token_count": _count_kind(tokens, "visual"),
            "long_token_count": _count_kind(tokens, "long_text"),
            "short_eviction_count": data.get("short_eviction_count", 0),
            "long_eviction_count": data.get("long_eviction_count", 0),
            "verbalized_insert_count": data.get("verbalized_insert_count", 0),
        }
        return ProgramNodeResult(
            value=value,
            state_update={"last_result": value},
            events=({
                "type": "providellm_interleaved_cache_readout",
                "frame_count": value["frame_count"],
                "cache_token_count": len(tokens),
            },),
        )

    raise ValueError(f"unknown ProVideLLM memory event: {kind}")


def build_providellm_memory_program() -> ResearchProgram:
    fidelity = PROVIDELLM_REFERENCE_FIDELITY
    return (
        MemoryProgramBuilder.create(
            program_id="providellm.multimodal-interleaved-cache",
            version=PROVIDELLM_PAPER_ERA_COMMIT[:12],
            state_schema="providellm.multimodal-interleaved-cache.state.v1",
            entrypoint="dispatch",
        )
        .custom(
            "dispatch",
            "providellm.memory.dispatch",
            configuration={
                "paper_uri": fidelity.paper_uri,
                "source_commit": PROVIDELLM_PAPER_ERA_COMMIT,
                "memory_concerns": (
                    MemoryConcern.WRITE.value,
                    MemoryConcern.CONSOLIDATION.value,
                    MemoryConcern.RETENTION.value,
                ),
                "cache_type": fidelity.cache_type,
                "long_term_token_type": fidelity.long_term_token_type,
                "short_term_token_type": fidelity.short_term_token_type,
                "long_term_marker": fidelity.long_term_marker,
                "single_entry_point": True,
                "separate_short_long_exits": True,
                "streaming_algorithm_source": "iccv-2025-paper-algorithms-1-2",
            },
            next_node="dispatch",
        )
        .build()
    )


PROVIDELLM_MEMORY_PROGRAM = build_providellm_memory_program()


def providellm_memory_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "providellm.memory.dispatch",
            _dispatch,
            canonical_digest({
                "operation": "providellm.memory.dispatch",
                "paper": "ICCV-2025",
                "algorithm": "multimodal-interleaved-cache",
                "implementation_revision": 1,
            }),
        ),
    )


def providellm_memory_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="providellm.multimodal-interleaved-cache",
        program=PROVIDELLM_MEMORY_PROGRAM,
        operations=providellm_memory_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=4,
        dependency_identity={
            "paper_uri": PROVIDELLM_REFERENCE_FIDELITY.paper_uri,
            "source_commit": PROVIDELLM_PAPER_ERA_COMMIT,
            "official_streaming_interleave_code_released": False,
        },
    )


__all__ = [
    "PROVIDELLM_MEMORY_PROGRAM",
    "build_providellm_memory_program",
    "providellm_memory_host",
    "providellm_memory_initial_data",
    "providellm_memory_operations",
]
