from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
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

from .fidelity import WORLDMM_REFERENCE_FIDELITY
from .source import WORLDMM_INITIAL_RELEASE_COMMIT


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _sequence(value: object, field_name: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(value)


class WorldMMMemoryType(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    VISUAL = "visual"


@dataclass(frozen=True, slots=True)
class WorldMMEvidenceItem:
    item_id: str
    memory_type: WorldMMMemoryType
    display_text: str = ""
    artifact_refs: tuple[str, ...] = ()
    metadata: JsonObject = field(default_factory=dict)
    item_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "item_id",
            _text(self.item_id, "WorldMM evidence item_id"),
        )
        if not isinstance(self.memory_type, WorldMMMemoryType):
            raise TypeError(
                "WorldMM evidence memory_type must be WorldMMMemoryType"
            )
        if type(self.display_text) is not str:
            raise TypeError("WorldMM evidence display_text must be text")
        if type(self.artifact_refs) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in self.artifact_refs
        ):
            raise TypeError(
                "WorldMM evidence artifact_refs must be a text tuple"
            )
        if not isinstance(self.metadata, Mapping):
            raise TypeError("WorldMM evidence metadata must be an object")
        object.__setattr__(self, "metadata", freeze_json(self.metadata))
        object.__setattr__(
            self,
            "item_digest",
            canonical_digest({
                "item_id": self.item_id,
                "memory_type": self.memory_type.value,
                "display_text": self.display_text,
                "artifact_refs": self.artifact_refs,
                "metadata": self.metadata,
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "item_id": self.item_id,
            "memory_type": self.memory_type.value,
            "display_text": self.display_text,
            "artifact_refs": self.artifact_refs,
            "metadata": self.metadata,
            "item_digest": self.item_digest,
        }


@dataclass(frozen=True, slots=True)
class WorldMMFacetIndexRequest:
    until_time: int
    source_commit: str = WORLDMM_INITIAL_RELEASE_COMMIT

    def __post_init__(self) -> None:
        if type(self.until_time) is not int or self.until_time < 1:
            raise ValueError("WorldMM until_time must be positive")
        if self.source_commit != WORLDMM_INITIAL_RELEASE_COMMIT:
            raise ValueError("WorldMM index source identity drifted")


@dataclass(frozen=True, slots=True)
class WorldMMFacetIndexResult:
    memory_type: WorldMMMemoryType
    indexed_time: int
    indexed_item_count: int
    provider_receipt: JsonValue = None
    index_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.memory_type, WorldMMMemoryType):
            raise TypeError("WorldMM index memory_type is invalid")
        if type(self.indexed_time) is not int or self.indexed_time < 1:
            raise ValueError("WorldMM indexed_time must be positive")
        if type(self.indexed_item_count) is not int or self.indexed_item_count < 0:
            raise ValueError(
                "WorldMM indexed_item_count must be non-negative"
            )
        object.__setattr__(
            self,
            "provider_receipt",
            freeze_json(self.provider_receipt),
        )
        object.__setattr__(
            self,
            "index_digest",
            canonical_digest({
                "memory_type": self.memory_type.value,
                "indexed_time": self.indexed_time,
                "indexed_item_count": self.indexed_item_count,
                "provider_receipt": self.provider_receipt,
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "memory_type": self.memory_type.value,
            "indexed_time": self.indexed_time,
            "indexed_item_count": self.indexed_item_count,
            "provider_receipt": self.provider_receipt,
            "index_digest": self.index_digest,
        }


@dataclass(frozen=True, slots=True)
class WorldMMFacetRetrieveRequest:
    memory_type: WorldMMMemoryType
    query: str
    indexed_time: int
    top_k: int
    excluded_item_ids: tuple[str, ...] = ()
    configuration: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.memory_type, WorldMMMemoryType):
            raise TypeError("WorldMM retrieval memory_type is invalid")
        if type(self.query) is not str:
            raise TypeError("WorldMM retrieval query must be text")
        if type(self.indexed_time) is not int or self.indexed_time < 1:
            raise ValueError(
                "WorldMM retrieval requires positive indexed_time"
            )
        if type(self.top_k) is not int or self.top_k < 1:
            raise ValueError("WorldMM retrieval top_k must be positive")
        if type(self.excluded_item_ids) is not tuple or any(
            type(value) is not str or not value
            for value in self.excluded_item_ids
        ):
            raise TypeError(
                "WorldMM excluded_item_ids must be a text tuple"
            )
        if len(self.excluded_item_ids) != len(set(self.excluded_item_ids)):
            raise ValueError(
                "WorldMM excluded_item_ids must be unique"
            )
        if not isinstance(self.configuration, Mapping):
            raise TypeError(
                "WorldMM retrieval configuration must be an object"
            )
        object.__setattr__(
            self,
            "configuration",
            freeze_json(self.configuration),
        )


@dataclass(frozen=True, slots=True)
class WorldMMFacetRetrieveResult:
    memory_type: WorldMMMemoryType
    query: str
    items: tuple[WorldMMEvidenceItem, ...]
    provider_receipt: JsonValue = None
    retrieval_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.memory_type, WorldMMMemoryType):
            raise TypeError("WorldMM result memory_type is invalid")
        if type(self.query) is not str:
            raise TypeError("WorldMM result query must be text")
        if type(self.items) is not tuple or any(
            not isinstance(item, WorldMMEvidenceItem)
            for item in self.items
        ):
            raise TypeError(
                "WorldMM retrieval items must be WorldMMEvidenceItem tuple"
            )
        if any(item.memory_type is not self.memory_type for item in self.items):
            raise ValueError("WorldMM retrieval facet result type drifted")
        object.__setattr__(
            self,
            "provider_receipt",
            freeze_json(self.provider_receipt),
        )
        object.__setattr__(
            self,
            "retrieval_digest",
            canonical_digest({
                "memory_type": self.memory_type.value,
                "query": self.query,
                "item_digests": tuple(
                    item.item_digest for item in self.items
                ),
                "provider_receipt": self.provider_receipt,
            }),
        )

    @property
    def artifact_refs(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            ref
            for item in self.items
            for ref in item.artifact_refs
        ))

    def payload(self) -> JsonObject:
        return {
            "memory_type": self.memory_type.value,
            "query": self.query,
            "items": tuple(item.payload() for item in self.items),
            "artifact_refs": self.artifact_refs,
            "provider_receipt": self.provider_receipt,
            "retrieval_digest": self.retrieval_digest,
        }


@runtime_checkable
class WorldMMMemoryFacetPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    @property
    def memory_type(self) -> WorldMMMemoryType: ...

    def index(
        self,
        request: WorldMMFacetIndexRequest,
    ) -> WorldMMFacetIndexResult: ...

    def retrieve(
        self,
        request: WorldMMFacetRetrieveRequest,
    ) -> WorldMMFacetRetrieveResult: ...


@dataclass(frozen=True, slots=True)
class WorldMMMemoryBinding:
    episodic: WorldMMMemoryFacetPort
    semantic: WorldMMMemoryFacetPort
    visual: WorldMMMemoryFacetPort
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        expected = (
            ("episodic", self.episodic, WorldMMMemoryType.EPISODIC),
            ("semantic", self.semantic, WorldMMMemoryType.SEMANTIC),
            ("visual", self.visual, WorldMMMemoryType.VISUAL),
        )
        identities: list[tuple[str, str]] = []
        for name, port, memory_type in expected:
            if not isinstance(port, WorldMMMemoryFacetPort):
                raise TypeError(
                    f"WorldMM {name} facet must satisfy WorldMMMemoryFacetPort"
                )
            if port.memory_type is not memory_type:
                raise ValueError(
                    f"WorldMM {name} facet memory type identity drifted"
                )
            identities.append((
                name,
                require_sha256(
                    port.identity_digest,
                    f"WorldMM {name} identity_digest",
                ),
            ))
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "source_commit": WORLDMM_INITIAL_RELEASE_COMMIT,
                "facet_identities": tuple(identities),
            }),
        )

    def facet(
        self,
        memory_type: WorldMMMemoryType,
    ) -> WorldMMMemoryFacetPort:
        if memory_type is WorldMMMemoryType.EPISODIC:
            return self.episodic
        if memory_type is WorldMMMemoryType.SEMANTIC:
            return self.semantic
        if memory_type is WorldMMMemoryType.VISUAL:
            return self.visual
        raise TypeError("unknown WorldMM memory type")


def worldmm_memory_initial_data() -> JsonObject:
    return {
        "source_commit": WORLDMM_INITIAL_RELEASE_COMMIT,
        "indexed_time": 0,
        "facet_index_digests": {},
        "retrieval_count": 0,
        "retrieved_item_ids": (),
        "last_result": None,
    }


def _event(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.payload)
    if not isinstance(decoded, dict):
        raise TypeError("WorldMM memory payload must be an object")
    event = decoded.get("event")
    if not isinstance(event, Mapping):
        raise TypeError("WorldMM memory requires event envelope")
    value = thaw_json(event)
    if not isinstance(value, dict):
        raise TypeError("WorldMM memory event must decode to an object")
    return value


def _data(request: ProgramNodeRequest) -> dict[str, object]:
    value = thaw_json(request.data)
    if not isinstance(value, dict):
        raise TypeError("WorldMM memory data must be an object")
    if value.get("source_commit") != WORLDMM_INITIAL_RELEASE_COMMIT:
        raise ValueError("WorldMM memory source identity drifted")
    return value


def _index(
    binding: WorldMMMemoryBinding,
    *,
    until_time: int,
) -> tuple[WorldMMFacetIndexResult, ...]:
    request = WorldMMFacetIndexRequest(until_time=until_time)
    rows = tuple(
        facet.index(request)
        for facet in (
            binding.episodic,
            binding.semantic,
            binding.visual,
        )
    )
    expected = (
        WorldMMMemoryType.EPISODIC,
        WorldMMMemoryType.SEMANTIC,
        WorldMMMemoryType.VISUAL,
    )
    if tuple(row.memory_type for row in rows) != expected:
        raise ValueError("WorldMM facet index result order drifted")
    if any(row.indexed_time != until_time for row in rows):
        raise ValueError(
            "WorldMM facets must share the same indexed_time boundary"
        )
    return rows


def _retrieval_configuration(
    memory_type: WorldMMMemoryType,
) -> tuple[int, JsonObject]:
    f = WORLDMM_REFERENCE_FIDELITY
    if memory_type is WorldMMMemoryType.EPISODIC:
        return f.episodic_public_top_k, {
            "granularities": f.episodic_granularities,
            "candidate_top_k": f.episodic_candidate_top_k,
            "inner_final_top_k": (
                f.episodic_public_top_k
                * f.episodic_inner_final_top_k_multiplier
            ),
            "rerank": "llm-multiscale-filter",
            "backend": "hipporag-per-granularity",
        }
    if memory_type is WorldMMMemoryType.SEMANTIC:
        return f.semantic_public_top_k, {
            "inner_top_k": (
                f.semantic_public_top_k
                * f.semantic_inner_top_k_multiplier
            ),
            "retrieval": f.semantic_retrieval,
            "ppr_damping": f.semantic_ppr_damping,
            "triple_score": f.semantic_triple_score,
        }
    if memory_type is WorldMMMemoryType.VISUAL:
        return f.visual_public_top_k, {
            "query_modes": f.visual_query_modes,
            "clip_seconds": f.visual_clip_seconds,
            "fps": f.visual_frame_fps,
            "max_frames": f.visual_max_frames,
        }
    raise TypeError("unknown WorldMM memory type")


def _dispatch(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, WorldMMMemoryBinding):
        raise TypeError(
            "WorldMM memory dispatch requires WorldMMMemoryBinding"
        )
    data = _data(request)
    event = _event(request)
    kind = _text(event.get("kind"), "WorldMM memory event kind")
    payload = event.get("payload", {})
    if not isinstance(payload, Mapping):
        raise TypeError("WorldMM event payload must be an object")
    payload = thaw_json(payload)
    if not isinstance(payload, dict):
        raise TypeError("WorldMM event payload must decode to object")

    if kind == "worldmm.memory.index":
        until_time = payload.get("until_time")
        if type(until_time) is not int or until_time < 1:
            raise ValueError("WorldMM index until_time must be positive")
        current = data.get("indexed_time", 0)
        if type(current) is not int or current < 0:
            raise ValueError("WorldMM indexed_time state is invalid")
        if current >= until_time:
            value = {
                "indexed_time": current,
                "no_op": True,
                "facet_index_digests": data.get(
                    "facet_index_digests",
                    {},
                ),
            }
            return ProgramNodeResult(
                value=value,
                state_update={"last_result": value},
                events=({
                    "type": "worldmm_memory_index_noop",
                    "indexed_time": current,
                    "requested_time": until_time,
                },),
            )
        rows = _index(binding, until_time=until_time)
        digests = {
            row.memory_type.value: row.index_digest
            for row in rows
        }
        value = {
            "indexed_time": until_time,
            "no_op": False,
            "facet_index_results": tuple(
                row.payload() for row in rows
            ),
            "facet_index_digests": digests,
        }
        return ProgramNodeResult(
            value=value,
            state_update={
                "indexed_time": until_time,
                "facet_index_digests": digests,
                "last_result": value,
            },
            events=({
                "type": "worldmm_memory_indexed",
                "indexed_time": until_time,
                "facet_index_digests": digests,
            },),
        )

    if kind == "worldmm.memory.retrieve":
        indexed_time = data.get("indexed_time", 0)
        if type(indexed_time) is not int or indexed_time < 1:
            raise RuntimeError(
                "WorldMM memory must be indexed before retrieval"
            )
        memory_type = WorldMMMemoryType(
            _text(
                payload.get("memory_type"),
                "WorldMM retrieval memory_type",
            )
        )
        query = payload.get("query")
        if type(query) is not str:
            raise TypeError("WorldMM retrieval query must be text")
        previous_ids = _sequence(
            data.get("retrieved_item_ids", ()),
            "WorldMM retrieved_item_ids",
        )
        excluded_ids = tuple(
            _text(value, "WorldMM retrieved item id")
            for value in previous_ids
        )
        top_k, configuration = _retrieval_configuration(memory_type)
        result = binding.facet(memory_type).retrieve(
            WorldMMFacetRetrieveRequest(
                memory_type=memory_type,
                query=query,
                indexed_time=indexed_time,
                top_k=top_k,
                excluded_item_ids=excluded_ids,
                configuration=configuration,
            )
        )
        if not isinstance(result, WorldMMFacetRetrieveResult):
            raise TypeError(
                "WorldMM facet must return WorldMMFacetRetrieveResult"
            )
        if (
            result.memory_type is not memory_type
            or result.query != query
        ):
            raise ValueError("WorldMM retrieval result identity drifted")
        result_ids = tuple(item.item_id for item in result.items)
        duplicates = tuple(
            item_id for item_id in result_ids
            if item_id in set(excluded_ids)
        )
        if duplicates:
            raise ValueError(
                "WorldMM facet returned already-retrieved items: "
                f"{duplicates}"
            )
        if len(result_ids) > top_k:
            raise ValueError(
                "WorldMM facet exceeded public retrieval top_k"
            )
        next_retrieved_ids = (*excluded_ids, *result_ids)
        retrieval_count = data.get("retrieval_count", 0)
        if type(retrieval_count) is not int or retrieval_count < 0:
            raise ValueError(
                "WorldMM retrieval_count state is invalid"
            )
        next_count = retrieval_count + 1
        value = result.payload()
        return ProgramNodeResult(
            value=value,
            state_update={
                "retrieval_count": next_count,
                "retrieved_item_ids": next_retrieved_ids,
                "last_result": value,
            },
            events=({
                "type": "worldmm_memory_retrieved",
                "sequence": next_count,
                "memory_type": memory_type.value,
                "query": query,
                "item_ids": tuple(
                    item.item_id for item in result.items
                ),
                "retrieval_digest": result.retrieval_digest,
            },),
            artifact_refs=result.artifact_refs,
        )

    raise ValueError(f"unknown WorldMM memory event: {kind}")


def build_worldmm_memory_program() -> ResearchProgram:
    f = WORLDMM_REFERENCE_FIDELITY
    return (
        MemoryProgramBuilder.create(
            program_id="worldmm.heterogeneous-multimodal-memory",
            version=WORLDMM_INITIAL_RELEASE_COMMIT[:12],
            state_schema="worldmm.multimodal-memory.state.v1",
            entrypoint="dispatch",
        )
        .custom(
            "dispatch",
            "worldmm.memory.dispatch",
            configuration={
                "source_commit": WORLDMM_INITIAL_RELEASE_COMMIT,
                "memory_concerns": (
                    MemoryConcern.INDEX.value,
                    MemoryConcern.RETRIEVAL.value,
                ),
                "memory_types": f.memory_types,
                "episodic_granularities": f.episodic_granularities,
                "top_k": (
                    ("episodic", f.episodic_public_top_k),
                    ("semantic", f.semantic_public_top_k),
                    ("visual", f.visual_public_top_k),
                ),
                "shared_index_boundary": True,
            },
            next_node="dispatch",
        )
        .build()
    )


WORLDMM_MEMORY_PROGRAM = build_worldmm_memory_program()


def worldmm_memory_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "worldmm.memory.dispatch",
            _dispatch,
            canonical_digest({
                "operation": "worldmm.memory.dispatch",
                "source_commit": WORLDMM_INITIAL_RELEASE_COMMIT,
                "implementation_revision": 1,
            }),
        ),
    )


def worldmm_memory_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="worldmm.heterogeneous-multimodal-memory",
        program=WORLDMM_MEMORY_PROGRAM,
        operations=worldmm_memory_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=4,
        dependency_identity={
            "source_commit": WORLDMM_INITIAL_RELEASE_COMMIT,
            "memory_types": WORLDMM_REFERENCE_FIDELITY.memory_types,
            "episodic_granularities": (
                WORLDMM_REFERENCE_FIDELITY.episodic_granularities
            ),
        },
    )


__all__ = [
    "WORLDMM_MEMORY_PROGRAM",
    "WorldMMEvidenceItem",
    "WorldMMFacetIndexRequest",
    "WorldMMFacetIndexResult",
    "WorldMMFacetRetrieveRequest",
    "WorldMMFacetRetrieveResult",
    "WorldMMMemoryBinding",
    "WorldMMMemoryFacetPort",
    "WorldMMMemoryType",
    "build_worldmm_memory_program",
    "worldmm_memory_host",
    "worldmm_memory_initial_data",
    "worldmm_memory_operations",
]
