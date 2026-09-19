from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineSnapshotStorePort,
    canonical_digest,
    freeze_json,
    require_sha256,
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

from .fidelity import VIDEOLLAMB_REFERENCE_FIDELITY
from .source import VIDEOLLAMB_PAPER_ERA_COMMIT


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(_text(row, field_name) for row in value)


@dataclass(frozen=True, slots=True)
class VideoLLaMBSegmentBridgeRequest:
    segment_feature_ref: str
    previous_memory_ref: str | None
    segment_index: int
    memory_token_count: int = 32
    bridge_layer_count: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "segment_feature_ref",
            _text(self.segment_feature_ref, "VideoLLaMB segment_feature_ref"),
        )
        if self.previous_memory_ref is not None:
            object.__setattr__(
                self,
                "previous_memory_ref",
                _text(self.previous_memory_ref, "VideoLLaMB previous_memory_ref"),
            )
        if type(self.segment_index) is not int or self.segment_index < 0:
            raise ValueError("VideoLLaMB segment_index must be non-negative")
        if self.memory_token_count != 32:
            raise ValueError("VideoLLaMB paper-era recurrent memory uses 32 tokens")
        if self.bridge_layer_count != VIDEOLLAMB_REFERENCE_FIDELITY.bridge_transformer_layers:
            raise ValueError("VideoLLaMB bridge layer count drifted")


@dataclass(frozen=True, slots=True)
class VideoLLaMBSegmentBridgeResult:
    projected_segment_ref: str
    read_memory_ref: str
    provider_receipt: JsonValue = None
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("projected_segment_ref", "read_memory_ref"):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), f"VideoLLaMB {name}"),
            )
        object.__setattr__(self, "provider_receipt", freeze_json(self.provider_receipt))
        object.__setattr__(
            self,
            "result_digest",
            canonical_digest({
                "projected_segment_ref": self.projected_segment_ref,
                "read_memory_ref": self.read_memory_ref,
                "provider_receipt": self.provider_receipt,
            }),
        )


@dataclass(frozen=True, slots=True)
class VideoLLaMBRetrievalRequest:
    read_memory_ref: str
    memory_cache_refs: tuple[str, ...]
    retrieval_layer_count: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "read_memory_ref",
            _text(self.read_memory_ref, "VideoLLaMB read_memory_ref"),
        )
        cache = _strings(self.memory_cache_refs, "VideoLLaMB memory_cache_refs")
        if not cache:
            raise ValueError("VideoLLaMB retrieval requires a non-empty memory cache")
        object.__setattr__(self, "memory_cache_refs", cache)
        if self.retrieval_layer_count != 1:
            raise ValueError("VideoLLaMB paper-era retriever uses one layer")


@dataclass(frozen=True, slots=True)
class VideoLLaMBRetrievalResult:
    refreshed_memory_ref: str
    provider_receipt: JsonValue = None
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "refreshed_memory_ref",
            _text(self.refreshed_memory_ref, "VideoLLaMB refreshed_memory_ref"),
        )
        object.__setattr__(self, "provider_receipt", freeze_json(self.provider_receipt))
        object.__setattr__(
            self,
            "result_digest",
            canonical_digest({
                "refreshed_memory_ref": self.refreshed_memory_ref,
                "provider_receipt": self.provider_receipt,
            }),
        )


@runtime_checkable
class VideoLLaMBMemoryBridgePort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def bridge(
        self,
        request: VideoLLaMBSegmentBridgeRequest,
    ) -> VideoLLaMBSegmentBridgeResult: ...

    def retrieve(
        self,
        request: VideoLLaMBRetrievalRequest,
    ) -> VideoLLaMBRetrievalResult: ...


@dataclass(frozen=True, slots=True)
class VideoLLaMBMemoryBinding:
    bridge: VideoLLaMBMemoryBridgePort
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.bridge, VideoLLaMBMemoryBridgePort):
            raise TypeError(
                "VideoLLaMB bridge must satisfy VideoLLaMBMemoryBridgePort"
            )
        identity = require_sha256(
            self.bridge.identity_digest,
            "VideoLLaMB bridge identity_digest",
        )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "source_commit": VIDEOLLAMB_PAPER_ERA_COMMIT,
                "bridge_identity": identity,
                "memory_tokens": 32,
                "bridge_layers": VIDEOLLAMB_REFERENCE_FIDELITY.bridge_transformer_layers,
                "retrieval_layers": 1,
            }),
        )


def videollamb_memory_initial_data() -> JsonObject:
    return {
        "source_commit": VIDEOLLAMB_PAPER_ERA_COMMIT,
        "segment_count": 0,
        "recurrent_memory_ref": None,
        "memory_cache_refs": (),
        "projected_segment_refs": (),
        "last_result": None,
    }


def _event(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.payload)
    if not isinstance(decoded, dict):
        raise TypeError("VideoLLaMB memory payload must be an object")
    event = decoded.get("event")
    if not isinstance(event, Mapping):
        raise TypeError("VideoLLaMB memory requires event envelope")
    value = thaw_json(event)
    if not isinstance(value, dict):
        raise TypeError("VideoLLaMB memory event must decode to an object")
    return value


def _data(request: ProgramNodeRequest) -> dict[str, object]:
    value = thaw_json(request.data)
    if not isinstance(value, dict):
        raise TypeError("VideoLLaMB memory data must be an object")
    if value.get("source_commit") != VIDEOLLAMB_PAPER_ERA_COMMIT:
        raise ValueError("VideoLLaMB source identity drifted")
    return value


def _dispatch(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, VideoLLaMBMemoryBinding):
        raise TypeError(
            "VideoLLaMB memory dispatch requires VideoLLaMBMemoryBinding"
        )
    data = _data(request)
    event = _event(request)
    kind = _text(event.get("kind"), "VideoLLaMB memory event kind")
    payload = event.get("payload", {})
    if not isinstance(payload, Mapping):
        raise TypeError("VideoLLaMB event payload must be an object")
    payload = thaw_json(payload)
    if not isinstance(payload, dict):
        raise TypeError("VideoLLaMB event payload must decode to an object")

    if kind == "videollamb.memory.segment":
        segment_ref = _text(
            payload.get("segment_feature_ref"),
            "VideoLLaMB segment_feature_ref",
        )
        segment_count = data.get("segment_count", 0)
        if type(segment_count) is not int or segment_count < 0:
            raise ValueError("VideoLLaMB segment_count state is invalid")
        previous_memory = data.get("recurrent_memory_ref")
        if previous_memory is not None:
            previous_memory = _text(
                previous_memory,
                "VideoLLaMB recurrent_memory_ref",
            )

        bridged = binding.bridge.bridge(
            VideoLLaMBSegmentBridgeRequest(
                segment_feature_ref=segment_ref,
                previous_memory_ref=previous_memory,
                segment_index=segment_count,
            )
        )
        if not isinstance(bridged, VideoLLaMBSegmentBridgeResult):
            raise TypeError(
                "VideoLLaMB bridge must return VideoLLaMBSegmentBridgeResult"
            )

        cache = (
            *_strings(
                data.get("memory_cache_refs", ()),
                "VideoLLaMB memory_cache_refs",
            ),
            bridged.read_memory_ref,
        )
        refreshed = binding.bridge.retrieve(
            VideoLLaMBRetrievalRequest(
                read_memory_ref=bridged.read_memory_ref,
                memory_cache_refs=cache,
            )
        )
        if not isinstance(refreshed, VideoLLaMBRetrievalResult):
            raise TypeError(
                "VideoLLaMB retriever must return VideoLLaMBRetrievalResult"
            )
        projected = (
            *_strings(
                data.get("projected_segment_refs", ()),
                "VideoLLaMB projected_segment_refs",
            ),
            bridged.projected_segment_ref,
        )
        next_count = segment_count + 1
        value = {
            "segment_index": segment_count,
            "projected_segment_ref": bridged.projected_segment_ref,
            "bridge_memory_ref": bridged.read_memory_ref,
            "recurrent_memory_ref": refreshed.refreshed_memory_ref,
            "memory_cache_size": len(cache),
            "bridge_result_digest": bridged.result_digest,
            "retrieval_result_digest": refreshed.result_digest,
        }
        return ProgramNodeResult(
            value=value,
            state_update={
                "segment_count": next_count,
                "recurrent_memory_ref": refreshed.refreshed_memory_ref,
                "memory_cache_refs": cache,
                "projected_segment_refs": projected,
                "last_result": value,
            },
            events=({
                "type": "videollamb_memory_segment_committed",
                "segment_index": segment_count,
                "memory_cache_size": len(cache),
                "bridge_result_digest": bridged.result_digest,
                "retrieval_result_digest": refreshed.result_digest,
            },),
        )

    if kind == "videollamb.memory.readout":
        value = {
            "segment_count": data.get("segment_count", 0),
            "recurrent_memory_ref": data.get("recurrent_memory_ref"),
            "memory_cache_refs": data.get("memory_cache_refs", ()),
            "projected_segment_refs": data.get("projected_segment_refs", ()),
        }
        return ProgramNodeResult(
            value=value,
            state_update={"last_result": value},
            events=({
                "type": "videollamb_memory_readout",
                "segment_count": data.get("segment_count", 0),
            },),
        )

    raise ValueError(f"unknown VideoLLaMB memory event: {kind}")


def build_videollamb_memory_program() -> ResearchProgram:
    fidelity = VIDEOLLAMB_REFERENCE_FIDELITY
    return (
        MemoryProgramBuilder.create(
            program_id="videollamb.recurrent-memory-bridge",
            version=VIDEOLLAMB_PAPER_ERA_COMMIT[:12],
            state_schema="videollamb.recurrent-memory.state.v1",
            entrypoint="dispatch",
        )
        .custom(
            "dispatch",
            "videollamb.memory.dispatch",
            configuration={
                "source_commit": VIDEOLLAMB_PAPER_ERA_COMMIT,
                "memory_concerns": (
                    MemoryConcern.CONSOLIDATION.value,
                    MemoryConcern.RETRIEVAL.value,
                    MemoryConcern.RETENTION.value,
                ),
                "scene_tiling": fidelity.scene_tiling,
                "memory_token_count": 32,
                "bridge_layer_count": fidelity.bridge_transformer_layers,
                "retrieval_layer_count": 1,
                "recurrence": (
                    "bridge_segment",
                    "append_read_memory_to_cache",
                    "retrieve_over_full_cache",
                    "carry_refreshed_memory_to_next_segment",
                ),
            },
            next_node="dispatch",
        )
        .build()
    )


VIDEOLLAMB_MEMORY_PROGRAM = build_videollamb_memory_program()


def videollamb_memory_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "videollamb.memory.dispatch",
            _dispatch,
            canonical_digest({
                "operation": "videollamb.memory.dispatch",
                "source_commit": VIDEOLLAMB_PAPER_ERA_COMMIT,
                "implementation_revision": 1,
            }),
        ),
    )


def videollamb_memory_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="videollamb.recurrent-memory-bridge",
        program=VIDEOLLAMB_MEMORY_PROGRAM,
        operations=videollamb_memory_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=4,
        dependency_identity={
            "source_commit": VIDEOLLAMB_PAPER_ERA_COMMIT,
            "memory_tokens": 32,
            "bridge_layers": VIDEOLLAMB_REFERENCE_FIDELITY.bridge_transformer_layers,
            "retrieval_layers": 1,
        },
    )


__all__ = [
    "VIDEOLLAMB_MEMORY_PROGRAM",
    "VideoLLaMBMemoryBinding",
    "VideoLLaMBMemoryBridgePort",
    "VideoLLaMBRetrievalRequest",
    "VideoLLaMBRetrievalResult",
    "VideoLLaMBSegmentBridgeRequest",
    "VideoLLaMBSegmentBridgeResult",
    "build_videollamb_memory_program",
    "videollamb_memory_host",
    "videollamb_memory_initial_data",
    "videollamb_memory_operations",
]
