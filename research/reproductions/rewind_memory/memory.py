from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.evidence.artifact.content.api import (
    TensorContentRef,
    TensorContentStorePort,
)
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

from .fidelity import REWIND_REFERENCE_FIDELITY


_MEMORY_SCHEMA = "rewind.memory-bank.tensor.v1"
_SUBCLIP_SCHEMA = "rewind.subclip-visual-features.tensor.v1"
_INSTRUCTION_SCHEMA = "rewind.instruction-embedding.tensor.v1"
_SELECTED_FRAME_SCHEMA = "rewind.selected-frame-features.tensor.v1"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _tensor_ref(value: object, field_name: str) -> TensorContentRef:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a tensor reference")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to an object")
    return TensorContentRef.from_payload(decoded)


def _verify(
    store: TensorContentStorePort,
    ref: TensorContentRef,
    field_name: str,
) -> None:
    if not store.verify(ref):
        raise ValueError(f"{field_name} failed immutable tensor verification")


@dataclass(frozen=True, slots=True)
class ReWindMemoryStepRequest:
    instruction_ref: TensorContentRef
    subclip_ref: TensorContentRef
    previous_memory_ref: TensorContentRef | None
    subclip_index: int
    processed_frame_count: int
    read_query_count: int = 32
    write_query_count: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.instruction_ref, TensorContentRef):
            raise TypeError("ReWind instruction_ref must be TensorContentRef")
        if not isinstance(self.subclip_ref, TensorContentRef):
            raise TypeError("ReWind subclip_ref must be TensorContentRef")
        if self.previous_memory_ref is not None and not isinstance(
            self.previous_memory_ref,
            TensorContentRef,
        ):
            raise TypeError(
                "ReWind previous_memory_ref must be TensorContentRef or None"
            )
        if type(self.subclip_index) is not int or self.subclip_index < 0:
            raise ValueError("ReWind subclip_index must be non-negative")
        if (
            type(self.processed_frame_count) is not int
            or self.processed_frame_count < 0
        ):
            raise ValueError(
                "ReWind processed_frame_count must be non-negative"
            )
        if (self.read_query_count, self.write_query_count) != (32, 2):
            raise ValueError("ReWind read/write query configuration drifted")


@dataclass(frozen=True, slots=True)
class ReWindMemoryStepResult:
    memory_ref: TensorContentRef
    added_frame_count: int
    model_receipt: JsonValue = None
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.memory_ref, TensorContentRef):
            raise TypeError("ReWind memory_ref must be TensorContentRef")
        if type(self.added_frame_count) is not int or self.added_frame_count < 1:
            raise ValueError("ReWind added_frame_count must be positive")
        object.__setattr__(self, "model_receipt", freeze_json(self.model_receipt))
        object.__setattr__(
            self,
            "result_digest",
            canonical_digest({
                "memory_tensor_digest": self.memory_ref.tensor_digest,
                "added_frame_count": self.added_frame_count,
                "model_receipt": self.model_receipt,
            }),
        )


@runtime_checkable
class ReWindLearnedMemoryPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def step(
        self,
        request: ReWindMemoryStepRequest,
    ) -> ReWindMemoryStepResult: ...


@dataclass(frozen=True, slots=True)
class ReWindSelectionRequest:
    instruction_ref: TensorContentRef
    memory_ref: TensorContentRef
    feature_buffer_refs: tuple[TensorContentRef, ...]
    frame_count: int
    first_stage_count: int
    final_frame_count: int
    selected_frame_tokens: int

    def __post_init__(self) -> None:
        if not isinstance(self.instruction_ref, TensorContentRef):
            raise TypeError("ReWind selection instruction_ref is invalid")
        if not isinstance(self.memory_ref, TensorContentRef):
            raise TypeError("ReWind selection memory_ref is invalid")
        if type(self.feature_buffer_refs) is not tuple or any(
            not isinstance(ref, TensorContentRef)
            for ref in self.feature_buffer_refs
        ):
            raise TypeError(
                "ReWind feature_buffer_refs must be TensorContentRef tuple"
            )
        if type(self.frame_count) is not int or self.frame_count < 1:
            raise ValueError("ReWind selection frame_count must be positive")
        if not 1 <= self.final_frame_count <= self.first_stage_count:
            raise ValueError("ReWind DFS selection counts are invalid")
        if self.first_stage_count > self.frame_count:
            raise ValueError("ReWind DFS first-stage count exceeds frames")
        if self.selected_frame_tokens != 32:
            raise ValueError("ReWind selected frame token count drifted")


@dataclass(frozen=True, slots=True)
class ReWindSelectionResult:
    instruction_selected_indices: tuple[int, ...]
    selected_indices: tuple[int, ...]
    selected_frame_refs: tuple[TensorContentRef, ...]
    selector_receipt: JsonValue = None
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, values in (
            ("instruction_selected_indices", self.instruction_selected_indices),
            ("selected_indices", self.selected_indices),
        ):
            if type(values) is not tuple or any(
                type(value) is not int or value < 0 for value in values
            ):
                raise TypeError(f"ReWind {name} must be non-negative int tuple")
            if len(values) != len(set(values)):
                raise ValueError(f"ReWind {name} must be unique")
        if type(self.selected_frame_refs) is not tuple or any(
            not isinstance(ref, TensorContentRef)
            for ref in self.selected_frame_refs
        ):
            raise TypeError(
                "ReWind selected_frame_refs must be TensorContentRef tuple"
            )
        object.__setattr__(
            self,
            "selector_receipt",
            freeze_json(self.selector_receipt),
        )
        object.__setattr__(
            self,
            "result_digest",
            canonical_digest({
                "instruction_selected_indices": (
                    self.instruction_selected_indices
                ),
                "selected_indices": self.selected_indices,
                "selected_frame_digests": tuple(
                    ref.tensor_digest for ref in self.selected_frame_refs
                ),
                "selector_receipt": self.selector_receipt,
            }),
        )


@runtime_checkable
class ReWindFrameSelectorPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def select(
        self,
        request: ReWindSelectionRequest,
    ) -> ReWindSelectionResult: ...


@dataclass(frozen=True, slots=True)
class ReWindMemoryBinding:
    tensor_store: TensorContentStorePort
    learned_memory: ReWindLearnedMemoryPort
    selector: ReWindFrameSelectorPort
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.tensor_store, TensorContentStorePort):
            raise TypeError("ReWind requires TensorContentStorePort")
        if not isinstance(self.learned_memory, ReWindLearnedMemoryPort):
            raise TypeError("ReWind requires learned memory port")
        if not isinstance(self.selector, ReWindFrameSelectorPort):
            raise TypeError("ReWind requires frame selector port")
        store_digest = require_sha256(
            self.tensor_store.identity_digest,
            "ReWind tensor store identity_digest",
        )
        memory_digest = require_sha256(
            self.learned_memory.identity_digest,
            "ReWind learned memory identity_digest",
        )
        selector_digest = require_sha256(
            self.selector.identity_digest,
            "ReWind selector identity_digest",
        )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "paper_revision": "cvpr-2025-camera-ready",
                "tensor_store_identity_digest": store_digest,
                "learned_memory_identity_digest": memory_digest,
                "selector_identity_digest": selector_digest,
                "implementation_revision": 1,
            }),
        )


def rewind_memory_initial_data(
    *,
    instruction_ref: TensorContentRef,
) -> JsonObject:
    if not isinstance(instruction_ref, TensorContentRef):
        raise TypeError("ReWind initial instruction_ref must be TensorContentRef")
    if instruction_ref.schema_id != _INSTRUCTION_SCHEMA:
        raise ValueError("ReWind instruction tensor schema drifted")
    return {
        "paper_revision": "cvpr-2025-camera-ready",
        "instruction_ref": instruction_ref.payload(),
        "memory_ref": None,
        "feature_buffer_refs": (),
        "processed_frame_count": 0,
        "processed_subclip_count": 0,
        "video_complete": False,
        "selection": None,
        "sequence": 0,
        "result": None,
    }


def _data(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.data)
    if not isinstance(decoded, dict):
        raise TypeError("ReWind memory state must be an object")
    if decoded.get("paper_revision") != "cvpr-2025-camera-ready":
        raise ValueError("ReWind paper identity drifted")
    return decoded


def _event(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.payload)
    if not isinstance(decoded, dict):
        raise TypeError("ReWind payload must be an object")
    event = decoded.get("event")
    if not isinstance(event, Mapping):
        raise TypeError("ReWind requires event envelope")
    event = thaw_json(event)
    if not isinstance(event, dict):
        raise TypeError("ReWind event must decode to an object")
    return event


def _feature_refs(value: object) -> tuple[TensorContentRef, ...]:
    decoded = thaw_json(value)
    if not isinstance(decoded, (tuple, list)):
        raise TypeError("ReWind feature buffer must be a sequence")
    return tuple(
        _tensor_ref(item, "ReWind feature buffer ref")
        for item in decoded
    )


def _dispatch(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, ReWindMemoryBinding):
        raise TypeError("ReWind memory requires ReWindMemoryBinding")
    data = _data(request)
    event = _event(request)
    kind = _text(event.get("kind"), "ReWind event kind")
    payload = event.get("payload", {})
    if not isinstance(payload, Mapping):
        raise TypeError("ReWind event payload must be an object")
    payload = thaw_json(payload)
    if not isinstance(payload, dict):
        raise TypeError("ReWind event payload must decode to object")

    instruction_ref = _tensor_ref(
        data.get("instruction_ref"),
        "ReWind instruction_ref",
    )
    _verify(binding.tensor_store, instruction_ref, "ReWind instruction")
    if instruction_ref.schema_id != _INSTRUCTION_SCHEMA:
        raise ValueError("ReWind instruction schema drifted")

    if kind == "rewind.memory.ingest":
        if data.get("video_complete") is True:
            raise RuntimeError("ReWind cannot ingest after final subclip")
        subclip_ref = _tensor_ref(
            payload.get("subclip_ref"),
            "ReWind subclip_ref",
        )
        _verify(binding.tensor_store, subclip_ref, "ReWind subclip")
        if subclip_ref.schema_id != _SUBCLIP_SCHEMA:
            raise ValueError("ReWind subclip tensor schema drifted")
        if not subclip_ref.shape or subclip_ref.shape[0] < 1:
            raise ValueError("ReWind subclip must contain frames")
        frame_count = int(subclip_ref.shape[0])
        previous = data.get("memory_ref")
        previous_ref = (
            None
            if previous is None
            else _tensor_ref(previous, "ReWind previous memory_ref")
        )
        if previous_ref is not None:
            _verify(binding.tensor_store, previous_ref, "ReWind memory")
        processed = data.get("processed_frame_count", 0)
        subclip_index = data.get("processed_subclip_count", 0)
        if type(processed) is not int or processed < 0:
            raise ValueError("ReWind processed_frame_count is invalid")
        if type(subclip_index) is not int or subclip_index < 0:
            raise ValueError("ReWind processed_subclip_count is invalid")

        result = binding.learned_memory.step(
            ReWindMemoryStepRequest(
                instruction_ref=instruction_ref,
                subclip_ref=subclip_ref,
                previous_memory_ref=previous_ref,
                subclip_index=subclip_index,
                processed_frame_count=processed,
            )
        )
        if not isinstance(result, ReWindMemoryStepResult):
            raise TypeError(
                "ReWind learned memory must return ReWindMemoryStepResult"
            )
        if result.added_frame_count != frame_count:
            raise ValueError(
                "ReWind learned memory added_frame_count drifted"
            )
        _verify(binding.tensor_store, result.memory_ref, "ReWind updated memory")
        if result.memory_ref.schema_id != _MEMORY_SCHEMA:
            raise ValueError("ReWind memory tensor schema drifted")
        next_frames = processed + frame_count
        if len(result.memory_ref.shape) < 2:
            raise ValueError("ReWind memory tensor must expose frame/token axes")
        if (
            result.memory_ref.shape[0] != next_frames
            or result.memory_ref.shape[1]
            != REWIND_REFERENCE_FIDELITY.memory_tokens_per_frame
        ):
            raise ValueError(
                "ReWind memory must store two tokens per processed frame"
            )
        final = payload.get("final", False)
        if type(final) is not bool:
            raise TypeError("ReWind final flag must be boolean")
        feature_refs = (
            *_feature_refs(data.get("feature_buffer_refs", ())),
            subclip_ref,
        )
        sequence = data.get("sequence", 0)
        if type(sequence) is not int or sequence < 0:
            raise ValueError("ReWind sequence is invalid")
        value = {
            "processed_frame_count": next_frames,
            "processed_subclip_count": subclip_index + 1,
            "memory_ref": result.memory_ref.payload(),
            "memory_token_count": (
                next_frames
                * REWIND_REFERENCE_FIDELITY.memory_tokens_per_frame
            ),
            "video_complete": final,
            "step_result_digest": result.result_digest,
        }
        return ProgramNodeResult(
            value=value,
            state_update={
                "memory_ref": result.memory_ref.payload(),
                "feature_buffer_refs": tuple(
                    ref.payload() for ref in feature_refs
                ),
                "processed_frame_count": next_frames,
                "processed_subclip_count": subclip_index + 1,
                "video_complete": final,
                "sequence": sequence + 1,
                "result": value,
            },
            events=({
                "type": "rewind_memory_subclip_ingested",
                "subclip_index": subclip_index,
                "added_frame_count": frame_count,
                "processed_frame_count": next_frames,
                "memory_tensor_digest": result.memory_ref.tensor_digest,
                "step_result_digest": result.result_digest,
                "video_complete": final,
            },),
            artifact_refs=(
                result.memory_ref.content.content_sha256,
                subclip_ref.content.content_sha256,
            ),
        )

    if kind == "rewind.memory.select":
        if data.get("video_complete") is not True:
            raise RuntimeError(
                "ReWind DFS requires completed Stage-1 memory"
            )
        memory_ref = _tensor_ref(
            data.get("memory_ref"),
            "ReWind memory_ref",
        )
        _verify(binding.tensor_store, memory_ref, "ReWind memory")
        feature_refs = _feature_refs(data.get("feature_buffer_refs", ()))
        for ref in feature_refs:
            _verify(binding.tensor_store, ref, "ReWind feature buffer")
        frame_count = data.get("processed_frame_count")
        if type(frame_count) is not int or frame_count < 1:
            raise ValueError("ReWind processed_frame_count is invalid")
        first_count = min(
            frame_count,
            REWIND_REFERENCE_FIDELITY.dfs_instruction_selection_count,
        )
        final_count = min(
            first_count,
            REWIND_REFERENCE_FIDELITY.dfs_final_frame_count,
        )
        result = binding.selector.select(
            ReWindSelectionRequest(
                instruction_ref=instruction_ref,
                memory_ref=memory_ref,
                feature_buffer_refs=feature_refs,
                frame_count=frame_count,
                first_stage_count=first_count,
                final_frame_count=final_count,
                selected_frame_tokens=(
                    REWIND_REFERENCE_FIDELITY.dfs_selected_frame_tokens
                ),
            )
        )
        if not isinstance(result, ReWindSelectionResult):
            raise TypeError(
                "ReWind selector must return ReWindSelectionResult"
            )
        if len(result.instruction_selected_indices) != first_count:
            raise ValueError("ReWind DFS first-stage selection count drifted")
        if len(result.selected_indices) != final_count:
            raise ValueError("ReWind DFS final selection count drifted")
        if len(result.selected_frame_refs) != final_count:
            raise ValueError("ReWind DFS selected frame refs drifted")
        first_set = set(result.instruction_selected_indices)
        if any(index not in first_set for index in result.selected_indices):
            raise ValueError(
                "ReWind final DFS frames must come from instruction selection"
            )
        if any(index >= frame_count for index in result.instruction_selected_indices):
            raise ValueError("ReWind DFS selected frame index out of bounds")
        for ref in result.selected_frame_refs:
            _verify(binding.tensor_store, ref, "ReWind selected frame")
            if ref.schema_id != _SELECTED_FRAME_SCHEMA:
                raise ValueError("ReWind selected frame schema drifted")
            if not ref.shape or ref.shape[0] != 32:
                raise ValueError(
                    "ReWind selected frames must be pooled to 32 tokens"
                )
        selection = {
            "instruction_selected_indices": (
                result.instruction_selected_indices
            ),
            "selected_indices": result.selected_indices,
            "selected_frame_refs": tuple(
                ref.payload() for ref in result.selected_frame_refs
            ),
            "selection_result_digest": result.result_digest,
            "selection_algorithm": (
                "instruction-attention-then-DPC-KNN"
            ),
        }
        value = {
            "memory_ref": memory_ref.payload(),
            **selection,
        }
        return ProgramNodeResult(
            value=value,
            state_update={
                "selection": selection,
                "result": value,
            },
            events=({
                "type": "rewind_dynamic_frames_selected",
                "first_stage_count": first_count,
                "final_frame_count": final_count,
                "selected_indices": result.selected_indices,
                "selection_result_digest": result.result_digest,
            },),
            artifact_refs=tuple(
                ref.content.content_sha256
                for ref in result.selected_frame_refs
            ),
        )

    if kind == "rewind.memory.read":
        memory_value = data.get("memory_ref")
        if memory_value is None:
            raise RuntimeError("ReWind memory is empty")
        memory_ref = _tensor_ref(memory_value, "ReWind memory_ref")
        _verify(binding.tensor_store, memory_ref, "ReWind memory")
        selection = thaw_json(data.get("selection"))
        selected_refs: tuple[TensorContentRef, ...] = ()
        if selection is not None:
            if not isinstance(selection, dict):
                raise TypeError("ReWind selection state must be an object")
            selected_refs = tuple(
                _tensor_ref(item, "ReWind selected frame ref")
                for item in selection.get("selected_frame_refs", ())
            )
            for ref in selected_refs:
                _verify(binding.tensor_store, ref, "ReWind selected frame")
        value = {
            "memory_ref": memory_ref.payload(),
            "selected_frame_refs": tuple(
                ref.payload() for ref in selected_refs
            ),
            "llm_input_order": (
                REWIND_REFERENCE_FIDELITY.llm_input_order
            ),
            "processed_frame_count": data.get("processed_frame_count"),
            "video_complete": data.get("video_complete"),
        }
        return ProgramNodeResult(
            value=value,
            state_update={"result": value},
            events=({
                "type": "rewind_memory_read",
                "memory_tensor_digest": memory_ref.tensor_digest,
                "selected_frame_count": len(selected_refs),
            },),
        )

    if kind == "rewind.memory.reset":
        value = {
            "cleared": True,
            "instruction_ref": instruction_ref.payload(),
        }
        return ProgramNodeResult(
            value=value,
            state_update={
                "memory_ref": None,
                "feature_buffer_refs": (),
                "processed_frame_count": 0,
                "processed_subclip_count": 0,
                "video_complete": False,
                "selection": None,
                "result": value,
            },
            events=({"type": "rewind_memory_reset"},),
        )

    raise ValueError(f"unsupported ReWind memory event: {kind}")


def build_rewind_memory_program() -> ResearchProgram:
    fidelity = REWIND_REFERENCE_FIDELITY
    return (
        MemoryProgramBuilder.create(
            program_id="rewind.instructed-multimodal-memory",
            version="cvpr2025",
            state_schema="rewind.instructed-memory.state.v1",
            entrypoint="dispatch",
        )
        .custom(
            "dispatch",
            "rewind.memory.dispatch",
            configuration={
                "memory_concerns": (
                    MemoryConcern.WRITE.value,
                    MemoryConcern.RETRIEVAL.value,
                    MemoryConcern.CONSOLIDATION.value,
                ),
                "read_queries": fidelity.read_query_count,
                "write_queries": fidelity.write_query_count,
                "memory_tokens_per_frame": fidelity.memory_tokens_per_frame,
                "dfs_first_stage": (
                    fidelity.dfs_instruction_selection_count
                ),
                "dfs_final_frames": fidelity.dfs_final_frame_count,
                "dfs_selected_frame_tokens": (
                    fidelity.dfs_selected_frame_tokens
                ),
                "source_authority": "cvpr-2025-camera-ready",
                "tensor_state": "content-addressed-reference-only",
            },
            next_node="dispatch",
        )
        .build()
    )


REWIND_MEMORY_PROGRAM = build_rewind_memory_program()


def rewind_memory_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "rewind.memory.dispatch",
            _dispatch,
            canonical_digest({
                "operation": "rewind.memory.dispatch",
                "paper_revision": "cvpr-2025-camera-ready",
                "implementation_revision": 1,
            }),
        ),
    )


def rewind_memory_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="rewind.instructed-multimodal-memory",
        program=REWIND_MEMORY_PROGRAM,
        operations=rewind_memory_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=4,
        dependency_identity={
            "paper_revision": "cvpr-2025-camera-ready",
            "paper_semantics_digest": canonical_digest({
                "read_queries": 32,
                "write_queries": 2,
                "dfs": (64, 8, 32),
                "selection": "instruction-attention-then-DPC-KNN",
                "implementation_revision": 1,
            }),
        },
    )


__all__ = [
    "REWIND_MEMORY_PROGRAM",
    "ReWindFrameSelectorPort",
    "ReWindLearnedMemoryPort",
    "ReWindMemoryBinding",
    "ReWindMemoryStepRequest",
    "ReWindMemoryStepResult",
    "ReWindSelectionRequest",
    "ReWindSelectionResult",
    "build_rewind_memory_program",
    "rewind_memory_host",
    "rewind_memory_initial_data",
    "rewind_memory_operations",
]
