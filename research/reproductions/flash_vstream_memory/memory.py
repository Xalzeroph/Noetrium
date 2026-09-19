from __future__ import annotations

import math
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
from noetrium_platform.research.execution.machines.api import (
    MemoryConcern,
    MemoryProgramBuilder,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgram,
    ResearchProgramHost,
)

from .fidelity import FLASH_VSTREAM_REFERENCE_FIDELITY


_PAPER_REVISION = "iccv-2025-camera-ready"
_HIGH_RES_SCHEMA = "flash-vstream.feature-bank.high-resolution.v1"
_LOW_RES_SCHEMA = "flash-vstream.feature-bank.low-resolution.v1"
_POSITION_SCHEMA = "flash-vstream.position-ids.v1"
_VISUAL_POSITION_SCHEMA = "flash-vstream.visual-position-ids.v1"
_CONTEXT_SCHEMA = "flash-vstream.context-memory.v1"
_AUGMENTATION_SCHEMA = "flash-vstream.augmentation-memory.v1"
_COMPOSED_SCHEMA = "flash-vstream.composed-memory.v1"
_COMPOSED_POSITION_SCHEMA = "flash-vstream.composed-position-ids.v1"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _tensor_ref(value: object, field_name: str) -> TensorContentRef:
    if isinstance(value, TensorContentRef):
        return value
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must be a tensor reference")
    return TensorContentRef.from_payload(decoded)


def _finite_tuple(
    value: object,
    field_name: str,
) -> tuple[float, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a numeric sequence")
    rows: list[float] = []
    for item in value:
        if (
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(float(item))
        ):
            raise ValueError(f"{field_name} values must be finite")
        rows.append(float(item))
    return tuple(rows)


def _indices(
    value: object,
    field_name: str,
) -> tuple[int, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be an integer sequence")
    rows = tuple(value)
    if any(type(item) is not int or item < 0 for item in rows):
        raise ValueError(f"{field_name} must contain non-negative integers")
    return rows


def _source_groups(
    value: object,
    *,
    source_slot_count: int,
) -> tuple[tuple[int, ...], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError("Flash-VStream source_groups must be a sequence")
    groups: list[tuple[int, ...]] = []
    for row in value:
        group = _indices(row, "Flash-VStream source group")
        if not group:
            raise ValueError("Flash-VStream source groups must be non-empty")
        if any(index >= source_slot_count for index in group):
            raise ValueError(
                "Flash-VStream source group references unknown source slot"
            )
        groups.append(group)
    return tuple(groups)


def _verify_ref(
    store: TensorContentStorePort,
    ref: TensorContentRef,
    *,
    field_name: str,
    schema_id: str | None = None,
) -> None:
    if schema_id is not None and ref.schema_id != schema_id:
        raise ValueError(
            f"{field_name} schema mismatch: {ref.schema_id!r}"
        )
    if not store.verify(ref):
        raise ValueError(f"{field_name} failed immutable tensor verification")


@dataclass(frozen=True, slots=True)
class FlashVStreamInputBundle:
    high_resolution_feature_ref: TensorContentRef
    low_resolution_feature_ref: TensorContentRef
    position_ids_ref: TensorContentRef
    visual_position_ids_ref: TensorContentRef
    source_temporal_slots: int
    input_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "high_resolution_feature_ref",
            "low_resolution_feature_ref",
            "position_ids_ref",
            "visual_position_ids_ref",
        ):
            if not isinstance(getattr(self, name), TensorContentRef):
                raise TypeError(f"Flash-VStream {name} must be TensorContentRef")
        if (
            type(self.source_temporal_slots) is not int
            or self.source_temporal_slots < 1
        ):
            raise ValueError(
                "Flash-VStream source_temporal_slots must be positive"
            )
        object.__setattr__(
            self,
            "input_digest",
            canonical_digest(self.payload(include_digest=False)),
        )

    def payload(self, *, include_digest: bool = True) -> JsonObject:
        value: JsonObject = {
            "high_resolution_feature_ref": (
                self.high_resolution_feature_ref.payload()
            ),
            "low_resolution_feature_ref": (
                self.low_resolution_feature_ref.payload()
            ),
            "position_ids_ref": self.position_ids_ref.payload(),
            "visual_position_ids_ref": (
                self.visual_position_ids_ref.payload()
            ),
            "source_temporal_slots": self.source_temporal_slots,
        }
        if include_digest:
            value["input_digest"] = self.input_digest
        return value

    @classmethod
    def from_payload(cls, value: object) -> "FlashVStreamInputBundle":
        decoded = thaw_json(value)
        if not isinstance(decoded, dict):
            raise TypeError("Flash-VStream input bundle must be an object")
        bundle = cls(
            high_resolution_feature_ref=_tensor_ref(
                decoded.get("high_resolution_feature_ref"),
                "Flash-VStream high-resolution feature ref",
            ),
            low_resolution_feature_ref=_tensor_ref(
                decoded.get("low_resolution_feature_ref"),
                "Flash-VStream low-resolution feature ref",
            ),
            position_ids_ref=_tensor_ref(
                decoded.get("position_ids_ref"),
                "Flash-VStream position ids ref",
            ),
            visual_position_ids_ref=_tensor_ref(
                decoded.get("visual_position_ids_ref"),
                "Flash-VStream visual position ids ref",
            ),
            source_temporal_slots=decoded.get("source_temporal_slots"),
        )
        supplied = decoded.get("input_digest")
        if supplied is not None and require_sha256(
            supplied,
            "Flash-VStream input_digest",
        ) != bundle.input_digest:
            raise ValueError("Flash-VStream input bundle digest mismatch")
        return bundle


@dataclass(frozen=True, slots=True)
class FlashVStreamContextCompressionRequest:
    low_resolution_feature_ref: TensorContentRef
    source_temporal_slots: int
    configured_length: int
    effective_packed_slots: int
    method: str
    pool_size: int
    pca_dim: int

    def __post_init__(self) -> None:
        if not isinstance(self.low_resolution_feature_ref, TensorContentRef):
            raise TypeError(
                "Flash-VStream context request requires tensor reference"
            )
        for name in (
            "source_temporal_slots",
            "configured_length",
            "effective_packed_slots",
            "pool_size",
            "pca_dim",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"Flash-VStream {name} must be positive")
        object.__setattr__(
            self,
            "method",
            _text(self.method, "Flash-VStream temporal method"),
        )


@dataclass(frozen=True, slots=True)
class FlashVStreamContextMemory:
    memory_ref: TensorContentRef
    weights: tuple[float, ...]
    temporal_positions: tuple[int, ...]
    source_groups: tuple[tuple[int, ...], ...]
    source_temporal_slots: int
    provider_receipt: JsonValue = None
    context_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.memory_ref, TensorContentRef):
            raise TypeError(
                "Flash-VStream context memory requires tensor reference"
            )
        weights = _finite_tuple(
            self.weights,
            "Flash-VStream context weights",
        )
        positions = _indices(
            self.temporal_positions,
            "Flash-VStream context temporal_positions",
        )
        if (
            type(self.source_temporal_slots) is not int
            or self.source_temporal_slots < 1
        ):
            raise ValueError(
                "Flash-VStream source_temporal_slots must be positive"
            )
        groups = _source_groups(
            self.source_groups,
            source_slot_count=self.source_temporal_slots,
        )
        slot_count = len(weights)
        if not slot_count:
            raise ValueError("Flash-VStream context memory must contain slots")
        if len(positions) != slot_count or len(groups) != slot_count:
            raise ValueError(
                "Flash-VStream context metadata must align with memory slots"
            )
        if any(index >= self.source_temporal_slots for index in positions):
            raise ValueError(
                "Flash-VStream context position exceeds source range"
            )
        object.__setattr__(self, "weights", weights)
        object.__setattr__(self, "temporal_positions", positions)
        object.__setattr__(self, "source_groups", groups)
        object.__setattr__(
            self,
            "provider_receipt",
            freeze_json(self.provider_receipt),
        )
        object.__setattr__(
            self,
            "context_digest",
            canonical_digest(self.payload(include_digest=False)),
        )

    @property
    def slot_count(self) -> int:
        return len(self.weights)

    def payload(self, *, include_digest: bool = True) -> JsonObject:
        value: JsonObject = {
            "memory_ref": self.memory_ref.payload(),
            "weights": self.weights,
            "temporal_positions": self.temporal_positions,
            "source_groups": self.source_groups,
            "source_temporal_slots": self.source_temporal_slots,
            "slot_count": self.slot_count,
            "provider_receipt": thaw_json(self.provider_receipt),
        }
        if include_digest:
            value["context_digest"] = self.context_digest
        return value

    @classmethod
    def from_payload(cls, value: object) -> "FlashVStreamContextMemory":
        decoded = thaw_json(value)
        if not isinstance(decoded, dict):
            raise TypeError("Flash-VStream context memory must be an object")
        result = cls(
            memory_ref=_tensor_ref(
                decoded.get("memory_ref"),
                "Flash-VStream context memory ref",
            ),
            weights=tuple(decoded.get("weights", ())),
            temporal_positions=tuple(
                decoded.get("temporal_positions", ())
            ),
            source_groups=tuple(
                tuple(group)
                for group in decoded.get("source_groups", ())
            ),
            source_temporal_slots=decoded.get("source_temporal_slots"),
            provider_receipt=decoded.get("provider_receipt"),
        )
        supplied = decoded.get("context_digest")
        if supplied is not None and require_sha256(
            supplied,
            "Flash-VStream context_digest",
        ) != result.context_digest:
            raise ValueError("Flash-VStream context digest mismatch")
        return result


@dataclass(frozen=True, slots=True)
class FlashVStreamAugmentationRequest:
    high_resolution_feature_ref: TensorContentRef
    low_resolution_feature_ref: TensorContentRef
    context_memory: FlashVStreamContextMemory
    configured_length: int
    effective_packed_slots: int
    method: str
    distance_metric: str

    def __post_init__(self) -> None:
        if not isinstance(self.high_resolution_feature_ref, TensorContentRef):
            raise TypeError(
                "Flash-VStream augmentation requires high-resolution ref"
            )
        if not isinstance(self.low_resolution_feature_ref, TensorContentRef):
            raise TypeError(
                "Flash-VStream augmentation requires low-resolution ref"
            )
        if not isinstance(self.context_memory, FlashVStreamContextMemory):
            raise TypeError(
                "Flash-VStream augmentation requires context memory"
            )
        for name in ("configured_length", "effective_packed_slots"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"Flash-VStream {name} must be positive")
        object.__setattr__(
            self,
            "method",
            _text(self.method, "Flash-VStream spatial method"),
        )
        object.__setattr__(
            self,
            "distance_metric",
            _text(
                self.distance_metric,
                "Flash-VStream spatial distance metric",
            ),
        )


@dataclass(frozen=True, slots=True)
class FlashVStreamAugmentationMemory:
    memory_ref: TensorContentRef
    source_positions: tuple[int, ...]
    anchor_context_indices: tuple[int, ...]
    source_temporal_slots: int
    provider_receipt: JsonValue = None
    augmentation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.memory_ref, TensorContentRef):
            raise TypeError(
                "Flash-VStream augmentation memory requires tensor ref"
            )
        positions = _indices(
            self.source_positions,
            "Flash-VStream augmentation source_positions",
        )
        anchors = _indices(
            self.anchor_context_indices,
            "Flash-VStream augmentation anchor_context_indices",
        )
        if len(positions) != len(anchors):
            raise ValueError(
                "Flash-VStream augmentation positions/anchors must align"
            )
        if (
            type(self.source_temporal_slots) is not int
            or self.source_temporal_slots < 1
        ):
            raise ValueError(
                "Flash-VStream source_temporal_slots must be positive"
            )
        if any(index >= self.source_temporal_slots for index in positions):
            raise ValueError(
                "Flash-VStream augmentation position exceeds source range"
            )
        object.__setattr__(self, "source_positions", positions)
        object.__setattr__(self, "anchor_context_indices", anchors)
        object.__setattr__(
            self,
            "provider_receipt",
            freeze_json(self.provider_receipt),
        )
        object.__setattr__(
            self,
            "augmentation_digest",
            canonical_digest(self.payload(include_digest=False)),
        )

    @property
    def slot_count(self) -> int:
        return len(self.source_positions)

    def payload(self, *, include_digest: bool = True) -> JsonObject:
        value: JsonObject = {
            "memory_ref": self.memory_ref.payload(),
            "source_positions": self.source_positions,
            "anchor_context_indices": self.anchor_context_indices,
            "source_temporal_slots": self.source_temporal_slots,
            "slot_count": self.slot_count,
            "provider_receipt": thaw_json(self.provider_receipt),
        }
        if include_digest:
            value["augmentation_digest"] = self.augmentation_digest
        return value

    @classmethod
    def from_payload(
        cls,
        value: object,
    ) -> "FlashVStreamAugmentationMemory":
        decoded = thaw_json(value)
        if not isinstance(decoded, dict):
            raise TypeError(
                "Flash-VStream augmentation memory must be an object"
            )
        result = cls(
            memory_ref=_tensor_ref(
                decoded.get("memory_ref"),
                "Flash-VStream augmentation memory ref",
            ),
            source_positions=tuple(decoded.get("source_positions", ())),
            anchor_context_indices=tuple(
                decoded.get("anchor_context_indices", ())
            ),
            source_temporal_slots=decoded.get("source_temporal_slots"),
            provider_receipt=decoded.get("provider_receipt"),
        )
        supplied = decoded.get("augmentation_digest")
        if supplied is not None and require_sha256(
            supplied,
            "Flash-VStream augmentation_digest",
        ) != result.augmentation_digest:
            raise ValueError("Flash-VStream augmentation digest mismatch")
        return result


@dataclass(frozen=True, slots=True)
class FlashVStreamCompositionRequest:
    context_memory: FlashVStreamContextMemory
    augmentation_memory: FlashVStreamAugmentationMemory
    position_ids_ref: TensorContentRef
    visual_position_ids_ref: TensorContentRef
    composition_order: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.context_memory, FlashVStreamContextMemory):
            raise TypeError(
                "Flash-VStream composition requires context memory"
            )
        if not isinstance(
            self.augmentation_memory,
            FlashVStreamAugmentationMemory,
        ):
            raise TypeError(
                "Flash-VStream composition requires augmentation memory"
            )
        for name in ("position_ids_ref", "visual_position_ids_ref"):
            if not isinstance(getattr(self, name), TensorContentRef):
                raise TypeError(
                    f"Flash-VStream {name} must be TensorContentRef"
                )
        if self.composition_order != (
            "augmentation_memory",
            "context_memory",
        ):
            raise ValueError(
                "Flash-VStream composition order must preserve DAM then CSM"
            )


@dataclass(frozen=True, slots=True)
class FlashVStreamComposedMemory:
    memory_ref: TensorContentRef
    position_ids_ref: TensorContentRef
    augmentation_slots: int
    context_slots: int
    composition_order: tuple[str, ...]
    provider_receipt: JsonValue = None
    composed_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.memory_ref, TensorContentRef):
            raise TypeError(
                "Flash-VStream composed memory requires tensor ref"
            )
        if not isinstance(self.position_ids_ref, TensorContentRef):
            raise TypeError(
                "Flash-VStream composed positions require tensor ref"
            )
        for name in ("augmentation_slots", "context_slots"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(
                    f"Flash-VStream {name} must be non-negative"
                )
        if self.context_slots < 1:
            raise ValueError(
                "Flash-VStream composed memory requires context slots"
            )
        if self.composition_order != (
            "augmentation_memory",
            "context_memory",
        ):
            raise ValueError(
                "Flash-VStream composed memory order drifted"
            )
        object.__setattr__(
            self,
            "provider_receipt",
            freeze_json(self.provider_receipt),
        )
        object.__setattr__(
            self,
            "composed_digest",
            canonical_digest(self.payload(include_digest=False)),
        )

    @property
    def total_slots(self) -> int:
        return self.augmentation_slots + self.context_slots

    def payload(self, *, include_digest: bool = True) -> JsonObject:
        value: JsonObject = {
            "memory_ref": self.memory_ref.payload(),
            "position_ids_ref": self.position_ids_ref.payload(),
            "augmentation_slots": self.augmentation_slots,
            "context_slots": self.context_slots,
            "total_slots": self.total_slots,
            "composition_order": self.composition_order,
            "provider_receipt": thaw_json(self.provider_receipt),
        }
        if include_digest:
            value["composed_digest"] = self.composed_digest
        return value


@runtime_checkable
class FlashVStreamContextCompressorPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def compress(
        self,
        request: FlashVStreamContextCompressionRequest,
    ) -> FlashVStreamContextMemory: ...


@runtime_checkable
class FlashVStreamAugmentationRetrieverPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def retrieve(
        self,
        request: FlashVStreamAugmentationRequest,
    ) -> FlashVStreamAugmentationMemory: ...


@runtime_checkable
class FlashVStreamComposerPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def compose(
        self,
        request: FlashVStreamCompositionRequest,
    ) -> FlashVStreamComposedMemory: ...


@dataclass(frozen=True, slots=True)
class FlashVStreamMemoryBinding:
    tensor_store: TensorContentStorePort
    context_compressor: FlashVStreamContextCompressorPort
    augmentation_retriever: FlashVStreamAugmentationRetrieverPort
    composer: FlashVStreamComposerPort
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.tensor_store, TensorContentStorePort):
            raise TypeError(
                "Flash-VStream binding requires TensorContentStorePort"
            )
        for name, port, protocol in (
            (
                "context_compressor",
                self.context_compressor,
                FlashVStreamContextCompressorPort,
            ),
            (
                "augmentation_retriever",
                self.augmentation_retriever,
                FlashVStreamAugmentationRetrieverPort,
            ),
            ("composer", self.composer, FlashVStreamComposerPort),
        ):
            if not isinstance(port, protocol):
                raise TypeError(
                    f"Flash-VStream binding requires {name} port"
                )
            require_sha256(
                port.identity_digest,
                f"Flash-VStream {name} identity_digest",
            )
        require_sha256(
            self.tensor_store.identity_digest,
            "Flash-VStream tensor store identity_digest",
        )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "paper_revision": _PAPER_REVISION,
                "tensor_store_identity_digest": (
                    self.tensor_store.identity_digest
                ),
                "context_compressor_identity_digest": (
                    self.context_compressor.identity_digest
                ),
                "augmentation_retriever_identity_digest": (
                    self.augmentation_retriever.identity_digest
                ),
                "composer_identity_digest": self.composer.identity_digest,
            }),
        )


def flash_vstream_memory_initial_data(
    bundle: FlashVStreamInputBundle,
) -> JsonObject:
    if not isinstance(bundle, FlashVStreamInputBundle):
        raise TypeError(
            "Flash-VStream initial data requires FlashVStreamInputBundle"
        )
    return {
        "paper_revision": _PAPER_REVISION,
        "input": bundle.payload(),
        "context_memory": None,
        "augmentation_memory": None,
        "composed_memory": None,
        "result": None,
    }


def _data(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.data)
    if not isinstance(decoded, dict):
        raise TypeError("Flash-VStream memory data must be an object")
    if decoded.get("paper_revision") != _PAPER_REVISION:
        raise ValueError("Flash-VStream paper identity drifted")
    return decoded


def _context_compress(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, FlashVStreamMemoryBinding):
        raise TypeError(
            "Flash-VStream context compression requires memory binding"
        )
    data = _data(request)
    bundle = FlashVStreamInputBundle.from_payload(data.get("input"))
    _verify_ref(
        binding.tensor_store,
        bundle.low_resolution_feature_ref,
        field_name="Flash-VStream low-resolution feature bank",
        schema_id=_LOW_RES_SCHEMA,
    )
    fidelity = FLASH_VSTREAM_REFERENCE_FIDELITY
    result = binding.context_compressor.compress(
        FlashVStreamContextCompressionRequest(
            low_resolution_feature_ref=bundle.low_resolution_feature_ref,
            source_temporal_slots=bundle.source_temporal_slots,
            configured_length=fidelity.temporal_config_length,
            effective_packed_slots=fidelity.temporal_effective_packed_slots,
            method=fidelity.temporal_method,
            pool_size=fidelity.temporal_pool_size,
            pca_dim=fidelity.temporal_pca_dim,
        )
    )
    if not isinstance(result, FlashVStreamContextMemory):
        raise TypeError(
            "Flash-VStream compressor must return context memory"
        )
    if result.source_temporal_slots != bundle.source_temporal_slots:
        raise ValueError(
            "Flash-VStream context source length drifted"
        )
    if (
        result.slot_count
        > fidelity.temporal_effective_packed_slots
    ):
        raise ValueError(
            "Flash-VStream context memory exceeds effective capacity"
        )
    _verify_ref(
        binding.tensor_store,
        result.memory_ref,
        field_name="Flash-VStream context memory",
        schema_id=_CONTEXT_SCHEMA,
    )
    return ProgramNodeResult(
        value=result.payload(),
        state_update={"context_memory": result.payload()},
        events=({
            "type": "flash_vstream_context_memory_compressed",
            "source_temporal_slots": bundle.source_temporal_slots,
            "context_slots": result.slot_count,
            "temporal_method": fidelity.temporal_method,
            "context_digest": result.context_digest,
            "source_groups": result.source_groups,
            "temporal_positions": result.temporal_positions,
        },),
        artifact_refs=(
            bundle.low_resolution_feature_ref.content.content_sha256,
            result.memory_ref.content.content_sha256,
        ),
    )


def _augmentation_retrieve(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, FlashVStreamMemoryBinding):
        raise TypeError(
            "Flash-VStream augmentation retrieval requires memory binding"
        )
    data = _data(request)
    bundle = FlashVStreamInputBundle.from_payload(data.get("input"))
    context = FlashVStreamContextMemory.from_payload(
        data.get("context_memory")
    )
    _verify_ref(
        binding.tensor_store,
        bundle.high_resolution_feature_ref,
        field_name="Flash-VStream high-resolution feature bank",
        schema_id=_HIGH_RES_SCHEMA,
    )
    _verify_ref(
        binding.tensor_store,
        bundle.low_resolution_feature_ref,
        field_name="Flash-VStream low-resolution feature bank",
        schema_id=_LOW_RES_SCHEMA,
    )
    fidelity = FLASH_VSTREAM_REFERENCE_FIDELITY
    result = binding.augmentation_retriever.retrieve(
        FlashVStreamAugmentationRequest(
            high_resolution_feature_ref=(
                bundle.high_resolution_feature_ref
            ),
            low_resolution_feature_ref=(
                bundle.low_resolution_feature_ref
            ),
            context_memory=context,
            configured_length=fidelity.spatial_config_length,
            effective_packed_slots=fidelity.spatial_effective_packed_slots,
            method=fidelity.spatial_method,
            distance_metric=fidelity.spatial_retrieval_metric,
        )
    )
    if not isinstance(result, FlashVStreamAugmentationMemory):
        raise TypeError(
            "Flash-VStream retriever must return augmentation memory"
        )
    if result.source_temporal_slots != bundle.source_temporal_slots:
        raise ValueError(
            "Flash-VStream augmentation source length drifted"
        )
    if (
        result.slot_count
        > fidelity.spatial_effective_packed_slots
    ):
        raise ValueError(
            "Flash-VStream augmentation memory exceeds effective capacity"
        )
    if any(
        index >= context.slot_count
        for index in result.anchor_context_indices
    ):
        raise ValueError(
            "Flash-VStream augmentation anchor exceeds context memory"
        )
    _verify_ref(
        binding.tensor_store,
        result.memory_ref,
        field_name="Flash-VStream augmentation memory",
        schema_id=_AUGMENTATION_SCHEMA,
    )
    return ProgramNodeResult(
        value=result.payload(),
        state_update={"augmentation_memory": result.payload()},
        events=({
            "type": "flash_vstream_augmentation_memory_retrieved",
            "augmentation_slots": result.slot_count,
            "spatial_method": fidelity.spatial_method,
            "distance_metric": fidelity.spatial_retrieval_metric,
            "source_positions": result.source_positions,
            "anchor_context_indices": result.anchor_context_indices,
            "augmentation_digest": result.augmentation_digest,
        },),
        artifact_refs=(
            bundle.high_resolution_feature_ref.content.content_sha256,
            result.memory_ref.content.content_sha256,
        ),
    )


def _compose(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, FlashVStreamMemoryBinding):
        raise TypeError(
            "Flash-VStream composition requires memory binding"
        )
    data = _data(request)
    bundle = FlashVStreamInputBundle.from_payload(data.get("input"))
    context = FlashVStreamContextMemory.from_payload(
        data.get("context_memory")
    )
    augmentation = FlashVStreamAugmentationMemory.from_payload(
        data.get("augmentation_memory")
    )
    for ref, field_name, schema in (
        (
            bundle.position_ids_ref,
            "Flash-VStream position ids",
            _POSITION_SCHEMA,
        ),
        (
            bundle.visual_position_ids_ref,
            "Flash-VStream visual position ids",
            _VISUAL_POSITION_SCHEMA,
        ),
    ):
        _verify_ref(
            binding.tensor_store,
            ref,
            field_name=field_name,
            schema_id=schema,
        )
    fidelity = FLASH_VSTREAM_REFERENCE_FIDELITY
    result = binding.composer.compose(
        FlashVStreamCompositionRequest(
            context_memory=context,
            augmentation_memory=augmentation,
            position_ids_ref=bundle.position_ids_ref,
            visual_position_ids_ref=bundle.visual_position_ids_ref,
            composition_order=fidelity.composition_order,
        )
    )
    if not isinstance(result, FlashVStreamComposedMemory):
        raise TypeError(
            "Flash-VStream composer must return composed memory"
        )
    if result.context_slots != context.slot_count:
        raise ValueError(
            "Flash-VStream composed context slot count drifted"
        )
    if result.augmentation_slots != augmentation.slot_count:
        raise ValueError(
            "Flash-VStream composed augmentation slot count drifted"
        )
    _verify_ref(
        binding.tensor_store,
        result.memory_ref,
        field_name="Flash-VStream composed memory",
        schema_id=_COMPOSED_SCHEMA,
    )
    _verify_ref(
        binding.tensor_store,
        result.position_ids_ref,
        field_name="Flash-VStream composed position ids",
        schema_id=_COMPOSED_POSITION_SCHEMA,
    )
    payload = {
        "paper_revision": _PAPER_REVISION,
        "input_digest": bundle.input_digest,
        "context_memory": context.payload(),
        "augmentation_memory": augmentation.payload(),
        "composed_memory": result.payload(),
        "memory_digest": canonical_digest({
            "input_digest": bundle.input_digest,
            "context_digest": context.context_digest,
            "augmentation_digest": augmentation.augmentation_digest,
            "composed_digest": result.composed_digest,
        }),
    }
    return ProgramNodeResult(
        value=payload,
        state_update={
            "composed_memory": result.payload(),
            "result": payload,
        },
        events=({
            "type": "flash_vstream_memory_composed",
            "context_slots": context.slot_count,
            "augmentation_slots": augmentation.slot_count,
            "total_slots": result.total_slots,
            "composition_order": result.composition_order,
            "composed_digest": result.composed_digest,
        },),
        artifact_refs=(
            context.memory_ref.content.content_sha256,
            augmentation.memory_ref.content.content_sha256,
            result.memory_ref.content.content_sha256,
            result.position_ids_ref.content.content_sha256,
        ),
    )


def build_flash_vstream_memory_program() -> ResearchProgram:
    fidelity = FLASH_VSTREAM_REFERENCE_FIDELITY
    return (
        MemoryProgramBuilder.create(
            program_id="flash-vstream.dual-flash-memory",
            version="iccv2025",
            state_schema="flash-vstream.dual-flash-memory.state.v1",
            entrypoint="context_compress",
        )
        .semantic(
            "context_compress",
            MemoryConcern.CONSOLIDATION,
            "flash_vstream.memory.context_compress",
            configuration={
                "configured_length": fidelity.temporal_config_length,
                "effective_packed_slots": (
                    fidelity.temporal_effective_packed_slots
                ),
                "method": fidelity.temporal_method,
                "pool_size": fidelity.temporal_pool_size,
            },
            next_node="augmentation_retrieve",
        )
        .semantic(
            "augmentation_retrieve",
            MemoryConcern.RETRIEVAL,
            "flash_vstream.memory.augmentation_retrieve",
            configuration={
                "configured_length": fidelity.spatial_config_length,
                "effective_packed_slots": (
                    fidelity.spatial_effective_packed_slots
                ),
                "method": fidelity.spatial_method,
                "distance_metric": fidelity.spatial_retrieval_metric,
            },
            next_node="compose",
        )
        .semantic(
            "compose",
            MemoryConcern.PROJECTION,
            "flash_vstream.memory.compose",
            configuration={
                "composition_order": fidelity.composition_order,
                "memory_aware_rope": fidelity.memory_aware_rope_enabled,
            },
        )
        .build()
    )


FLASH_VSTREAM_MEMORY_PROGRAM = build_flash_vstream_memory_program()


def flash_vstream_memory_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "flash_vstream.memory.context_compress",
            _context_compress,
            canonical_digest({
                "operation": "flash_vstream.memory.context_compress",
                "paper_revision": _PAPER_REVISION,
                "implementation_revision": 1,
            }),
        ),
        ResearchHostOperation(
            "flash_vstream.memory.augmentation_retrieve",
            _augmentation_retrieve,
            canonical_digest({
                "operation": "flash_vstream.memory.augmentation_retrieve",
                "paper_revision": _PAPER_REVISION,
                "implementation_revision": 1,
            }),
        ),
        ResearchHostOperation(
            "flash_vstream.memory.compose",
            _compose,
            canonical_digest({
                "operation": "flash_vstream.memory.compose",
                "paper_revision": _PAPER_REVISION,
                "implementation_revision": 1,
            }),
        ),
    )


def flash_vstream_memory_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    fidelity = FLASH_VSTREAM_REFERENCE_FIDELITY
    return ResearchProgramHost(
        host_id="flash-vstream.dual-flash-memory",
        program=FLASH_VSTREAM_MEMORY_PROGRAM,
        operations=flash_vstream_memory_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=5,
        dependency_identity={
            "paper_revision": _PAPER_REVISION,
            "memory_semantics_digest": canonical_digest({
                "context_memory": {
                    "configured_length": fidelity.temporal_config_length,
                    "effective_packed_slots": (
                        fidelity.temporal_effective_packed_slots
                    ),
                    "method": fidelity.temporal_method,
                },
                "augmentation_memory": {
                    "configured_length": fidelity.spatial_config_length,
                    "effective_packed_slots": (
                        fidelity.spatial_effective_packed_slots
                    ),
                    "method": fidelity.spatial_method,
                    "metric": fidelity.spatial_retrieval_metric,
                },
                "composition_order": fidelity.composition_order,
                "memory_aware_rope": fidelity.memory_aware_rope_enabled,
            }),
        },
    )


__all__ = [
    "FLASH_VSTREAM_MEMORY_PROGRAM",
    "FlashVStreamAugmentationMemory",
    "FlashVStreamAugmentationRequest",
    "FlashVStreamAugmentationRetrieverPort",
    "FlashVStreamComposedMemory",
    "FlashVStreamComposerPort",
    "FlashVStreamCompositionRequest",
    "FlashVStreamContextCompressionRequest",
    "FlashVStreamContextCompressorPort",
    "FlashVStreamContextMemory",
    "FlashVStreamInputBundle",
    "FlashVStreamMemoryBinding",
    "build_flash_vstream_memory_program",
    "flash_vstream_memory_host",
    "flash_vstream_memory_initial_data",
    "flash_vstream_memory_operations",
]
