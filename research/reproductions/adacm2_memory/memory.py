from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
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

from .fidelity import (
    ADACM2_REFERENCE_FIDELITY,
    AdaCM2PartitionInterpretation,
)


_KEY_SCHEMA = "adacm2.key-cache.tensor.v1"
_VALUE_SCHEMA = "adacm2.value-cache.tensor.v1"
_FRAME_KEY_SCHEMA = "adacm2.frame-key.tensor.v1"
_FRAME_VALUE_SCHEMA = "adacm2.frame-value.tensor.v1"
_QUERY_TEXT_SCHEMA = "adacm2.query-text.tensor.v1"


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


def _tokens(value: object, field_name: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a token sequence")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class AdaCM2ReductionSpec:
    interpretation: AdaCM2PartitionInterpretation
    alpha: float = 0.1
    beta: float = 0.1
    split_rounding: str = "floor-min-one"
    reserve_rounding: str = "ceil-min-one"

    def __post_init__(self) -> None:
        if not isinstance(
            self.interpretation,
            AdaCM2PartitionInterpretation,
        ):
            raise TypeError(
                "AdaCM2 interpretation must be AdaCM2PartitionInterpretation"
            )
        for name, value in (("alpha", self.alpha), ("beta", self.beta)):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0.0 < float(value) < 1.0
            ):
                raise ValueError(f"AdaCM2 {name} must be in (0, 1)")
        if self.split_rounding != "floor-min-one":
            raise ValueError("AdaCM2 split rounding drifted")
        if self.reserve_rounding != "ceil-min-one":
            raise ValueError("AdaCM2 reserve rounding drifted")

    @property
    def previous_fraction(self) -> float:
        if self.interpretation is AdaCM2PartitionInterpretation.EQ6_LITERAL:
            return float(self.alpha)
        if (
            self.interpretation
            is AdaCM2PartitionInterpretation.EQ8_CONSISTENT
        ):
            return 1.0 - float(self.alpha)
        raise TypeError("unknown AdaCM2 partition interpretation")

    @property
    def recent_fraction(self) -> float:
        return 1.0 - self.previous_fraction

    @property
    def operational_retention_factor(self) -> float:
        return (
            self.recent_fraction
            + self.previous_fraction * float(self.beta)
        )

    @property
    def stated_theoretical_retention_factor(self) -> float:
        return float(self.alpha) + (
            1.0 - float(self.alpha)
        ) * float(self.beta)

    @property
    def spec_digest(self) -> str:
        return canonical_digest({
            "interpretation": self.interpretation.value,
            "alpha": float(self.alpha),
            "beta": float(self.beta),
            "split_rounding": self.split_rounding,
            "reserve_rounding": self.reserve_rounding,
            "operational_retention_factor": (
                self.operational_retention_factor
            ),
            "stated_theoretical_retention_factor": (
                self.stated_theoretical_retention_factor
            ),
        })


@dataclass(frozen=True, slots=True)
class AdaCM2AttentionRequest:
    layer_id: str
    previous_key_ref: TensorContentRef
    query_text_ref: TensorContentRef
    token_count: int
    frame_index: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "layer_id",
            _text(self.layer_id, "AdaCM2 layer_id"),
        )
        if not isinstance(self.previous_key_ref, TensorContentRef):
            raise TypeError("AdaCM2 previous_key_ref must be TensorContentRef")
        if not isinstance(self.query_text_ref, TensorContentRef):
            raise TypeError("AdaCM2 query_text_ref must be TensorContentRef")
        if type(self.token_count) is not int or self.token_count < 1:
            raise ValueError("AdaCM2 token_count must be positive")
        if type(self.frame_index) is not int or self.frame_index < 0:
            raise ValueError("AdaCM2 frame_index must be non-negative")


@dataclass(frozen=True, slots=True)
class AdaCM2AttentionScores:
    scores: tuple[float, ...]
    model_receipt: JsonValue = None
    score_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.scores) is not tuple or not self.scores:
            raise ValueError("AdaCM2 attention scores must be non-empty tuple")
        parsed: list[float] = []
        for value in self.scores:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError("AdaCM2 attention scores must be finite")
            parsed.append(float(value))
        object.__setattr__(self, "scores", tuple(parsed))
        object.__setattr__(self, "model_receipt", freeze_json(self.model_receipt))
        object.__setattr__(
            self,
            "score_digest",
            canonical_digest({
                "scores": self.scores,
                "model_receipt": self.model_receipt,
            }),
        )


@runtime_checkable
class AdaCM2CrossModalAttentionPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def score(
        self,
        request: AdaCM2AttentionRequest,
    ) -> AdaCM2AttentionScores: ...


@dataclass(frozen=True, slots=True)
class AdaCM2ReductionReceipt:
    interpretation: AdaCM2PartitionInterpretation
    before_length: int
    previous_length: int
    recent_length: int
    retained_previous_length: int
    retained_previous_indices: tuple[int, ...]
    after_length: int
    score_digest: str
    operational_retention_factor: float
    stated_theoretical_retention_factor: float
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(
            self.interpretation,
            AdaCM2PartitionInterpretation,
        ):
            raise TypeError("AdaCM2 receipt interpretation is invalid")
        for name, value in (
            ("before_length", self.before_length),
            ("previous_length", self.previous_length),
            ("recent_length", self.recent_length),
            ("retained_previous_length", self.retained_previous_length),
            ("after_length", self.after_length),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"AdaCM2 {name} must be non-negative")
        if self.before_length != self.previous_length + self.recent_length:
            raise ValueError("AdaCM2 partition lengths do not sum")
        if (
            self.after_length
            != self.retained_previous_length + self.recent_length
        ):
            raise ValueError("AdaCM2 reduced lengths do not sum")
        if len(self.retained_previous_indices) != self.retained_previous_length:
            raise ValueError("AdaCM2 retained index count drifted")
        require_sha256(self.score_digest, "AdaCM2 score_digest")
        object.__setattr__(
            self,
            "receipt_digest",
            canonical_digest({
                "interpretation": self.interpretation.value,
                "before_length": self.before_length,
                "previous_length": self.previous_length,
                "recent_length": self.recent_length,
                "retained_previous_length": self.retained_previous_length,
                "retained_previous_indices": self.retained_previous_indices,
                "after_length": self.after_length,
                "score_digest": self.score_digest,
                "operational_retention_factor": (
                    self.operational_retention_factor
                ),
                "stated_theoretical_retention_factor": (
                    self.stated_theoretical_retention_factor
                ),
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "interpretation": self.interpretation.value,
            "before_length": self.before_length,
            "previous_length": self.previous_length,
            "recent_length": self.recent_length,
            "retained_previous_length": self.retained_previous_length,
            "retained_previous_indices": self.retained_previous_indices,
            "after_length": self.after_length,
            "score_digest": self.score_digest,
            "operational_retention_factor": self.operational_retention_factor,
            "stated_theoretical_retention_factor": (
                self.stated_theoretical_retention_factor
            ),
            "receipt_digest": self.receipt_digest,
        }


def adacm2_partition_lengths(
    cache_length: int,
    spec: AdaCM2ReductionSpec,
) -> tuple[int, int]:
    if type(cache_length) is not int or cache_length < 1:
        raise ValueError("AdaCM2 cache_length must be positive")
    if not isinstance(spec, AdaCM2ReductionSpec):
        raise TypeError("AdaCM2 partition requires reduction spec")
    if cache_length == 1:
        return (0, 1)
    previous = max(
        1,
        int(math.floor(cache_length * spec.previous_fraction)),
    )
    previous = min(previous, cache_length - 1)
    return previous, cache_length - previous


def reduce_adacm2_cache(
    keys: tuple[object, ...],
    values: tuple[object, ...],
    scores: AdaCM2AttentionScores,
    *,
    spec: AdaCM2ReductionSpec,
) -> tuple[
    tuple[object, ...],
    tuple[object, ...],
    AdaCM2ReductionReceipt,
]:
    if type(keys) is not tuple or type(values) is not tuple:
        raise TypeError("AdaCM2 K/V caches must be tuples")
    if len(keys) != len(values) or not keys:
        raise ValueError("AdaCM2 K/V cache lengths must match and be non-empty")
    previous_length, recent_length = adacm2_partition_lengths(
        len(keys),
        spec,
    )
    if previous_length == 0:
        receipt = AdaCM2ReductionReceipt(
            interpretation=spec.interpretation,
            before_length=1,
            previous_length=0,
            recent_length=1,
            retained_previous_length=0,
            retained_previous_indices=(),
            after_length=1,
            score_digest=canonical_digest({"scores": ()}),
            operational_retention_factor=spec.operational_retention_factor,
            stated_theoretical_retention_factor=(
                spec.stated_theoretical_retention_factor
            ),
        )
        return keys, values, receipt
    if len(scores.scores) != previous_length:
        raise ValueError(
            "AdaCM2 attention score count must equal previous cache length"
        )
    keep = max(
        1,
        int(math.ceil(previous_length * float(spec.beta))),
    )
    ranked = sorted(
        range(previous_length),
        key=lambda index: (-scores.scores[index], index),
    )[:keep]
    retained_indices = tuple(sorted(ranked))
    recent_start = previous_length
    next_keys = tuple(keys[index] for index in retained_indices) + keys[
        recent_start:
    ]
    next_values = tuple(values[index] for index in retained_indices) + values[
        recent_start:
    ]
    receipt = AdaCM2ReductionReceipt(
        interpretation=spec.interpretation,
        before_length=len(keys),
        previous_length=previous_length,
        recent_length=recent_length,
        retained_previous_length=keep,
        retained_previous_indices=retained_indices,
        after_length=len(next_keys),
        score_digest=scores.score_digest,
        operational_retention_factor=spec.operational_retention_factor,
        stated_theoretical_retention_factor=(
            spec.stated_theoretical_retention_factor
        ),
    )
    return next_keys, next_values, receipt


@dataclass(frozen=True, slots=True)
class AdaCM2MemoryBinding:
    tensor_store: TensorContentStorePort
    attention: AdaCM2CrossModalAttentionPort
    spec: AdaCM2ReductionSpec
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.tensor_store, TensorContentStorePort):
            raise TypeError("AdaCM2 requires TensorContentStorePort")
        if not isinstance(self.attention, AdaCM2CrossModalAttentionPort):
            raise TypeError("AdaCM2 requires cross-modal attention port")
        if not isinstance(self.spec, AdaCM2ReductionSpec):
            raise TypeError("AdaCM2 requires reduction spec")
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "paper_revision": "cvpr-2025-camera-ready",
                "tensor_store_identity_digest": require_sha256(
                    self.tensor_store.identity_digest,
                    "AdaCM2 tensor store identity_digest",
                ),
                "attention_identity_digest": require_sha256(
                    self.attention.identity_digest,
                    "AdaCM2 attention identity_digest",
                ),
                "reduction_spec_digest": self.spec.spec_digest,
                "implementation_revision": 1,
            }),
        )


def adacm2_memory_initial_data(
    *,
    query_text_ref: TensorContentRef,
    interpretation: AdaCM2PartitionInterpretation,
) -> JsonObject:
    if not isinstance(query_text_ref, TensorContentRef):
        raise TypeError("AdaCM2 query_text_ref must be TensorContentRef")
    if query_text_ref.schema_id != _QUERY_TEXT_SCHEMA:
        raise ValueError("AdaCM2 query/text tensor schema drifted")
    if not isinstance(interpretation, AdaCM2PartitionInterpretation):
        raise TypeError("AdaCM2 partition interpretation is invalid")
    return {
        "paper_revision": "cvpr-2025-camera-ready",
        "query_text_ref": query_text_ref.payload(),
        "interpretation": interpretation.value,
        "layers": (),
        "frame_index": 0,
        "sequence": 0,
        "result": None,
    }


def _data(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.data)
    if not isinstance(decoded, dict):
        raise TypeError("AdaCM2 state must be an object")
    if decoded.get("paper_revision") != "cvpr-2025-camera-ready":
        raise ValueError("AdaCM2 paper identity drifted")
    return decoded


def _event(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.payload)
    if not isinstance(decoded, dict):
        raise TypeError("AdaCM2 payload must be an object")
    event = decoded.get("event")
    if not isinstance(event, Mapping):
        raise TypeError("AdaCM2 requires event envelope")
    event = thaw_json(event)
    if not isinstance(event, dict):
        raise TypeError("AdaCM2 event must decode to object")
    return event


def _layer_rows(value: object) -> list[dict[str, object]]:
    decoded = thaw_json(value)
    if not isinstance(decoded, (tuple, list)):
        raise TypeError("AdaCM2 layers must be a sequence")
    rows: list[dict[str, object]] = []
    for row in decoded:
        if not isinstance(row, dict):
            raise TypeError("AdaCM2 layer state row must be an object")
        rows.append(row)
    return rows


def _cache_tokens(
    store: TensorContentStorePort,
    ref: TensorContentRef,
    *,
    schema_id: str,
    field_name: str,
) -> tuple[object, ...]:
    _verify(store, ref, field_name)
    if ref.schema_id != schema_id:
        raise ValueError(f"{field_name} schema drifted")
    return _tokens(store.get(ref), field_name)


def _store_cache(
    store: TensorContentStorePort,
    values: tuple[object, ...],
    *,
    schema_id: str,
) -> TensorContentRef:
    return store.put(values, schema_id=schema_id)


def _dispatch(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, AdaCM2MemoryBinding):
        raise TypeError("AdaCM2 memory requires AdaCM2MemoryBinding")
    data = _data(request)
    event = _event(request)
    kind = _text(event.get("kind"), "AdaCM2 event kind")
    payload = event.get("payload", {})
    if not isinstance(payload, Mapping):
        raise TypeError("AdaCM2 event payload must be an object")
    payload = thaw_json(payload)
    if not isinstance(payload, dict):
        raise TypeError("AdaCM2 event payload must decode to object")

    interpretation = AdaCM2PartitionInterpretation(
        _text(data.get("interpretation"), "AdaCM2 interpretation")
    )
    if interpretation is not binding.spec.interpretation:
        raise ValueError("AdaCM2 reduction interpretation drifted")

    query_text_ref = _tensor_ref(
        data.get("query_text_ref"),
        "AdaCM2 query_text_ref",
    )
    _verify(binding.tensor_store, query_text_ref, "AdaCM2 query/text")
    layers = _layer_rows(data.get("layers", ()))

    if kind == "adacm2.cache.update":
        layer_id = _text(payload.get("layer_id"), "AdaCM2 layer_id")
        frame_key_ref = _tensor_ref(
            payload.get("key_ref"),
            "AdaCM2 frame key_ref",
        )
        frame_value_ref = _tensor_ref(
            payload.get("value_ref"),
            "AdaCM2 frame value_ref",
        )
        frame_keys = _cache_tokens(
            binding.tensor_store,
            frame_key_ref,
            schema_id=_FRAME_KEY_SCHEMA,
            field_name="AdaCM2 frame keys",
        )
        frame_values = _cache_tokens(
            binding.tensor_store,
            frame_value_ref,
            schema_id=_FRAME_VALUE_SCHEMA,
            field_name="AdaCM2 frame values",
        )
        if len(frame_keys) != len(frame_values):
            raise ValueError("AdaCM2 frame K/V token count drifted")

        existing = next(
            (row for row in layers if row.get("layer_id") == layer_id),
            None,
        )
        if existing is None:
            prior_keys: tuple[object, ...] = ()
            prior_values: tuple[object, ...] = ()
            frames_seen = 0
        else:
            prior_key_ref = _tensor_ref(
                existing.get("key_ref"),
                "AdaCM2 layer key_ref",
            )
            prior_value_ref = _tensor_ref(
                existing.get("value_ref"),
                "AdaCM2 layer value_ref",
            )
            prior_keys = _cache_tokens(
                binding.tensor_store,
                prior_key_ref,
                schema_id=_KEY_SCHEMA,
                field_name="AdaCM2 key cache",
            )
            prior_values = _cache_tokens(
                binding.tensor_store,
                prior_value_ref,
                schema_id=_VALUE_SCHEMA,
                field_name="AdaCM2 value cache",
            )
            frames_seen = existing.get("frames_seen", 0)
            if type(frames_seen) is not int or frames_seen < 0:
                raise ValueError("AdaCM2 frames_seen is invalid")

        combined_keys = (*prior_keys, *frame_keys)
        combined_values = (*prior_values, *frame_values)
        previous_length, _ = adacm2_partition_lengths(
            len(combined_keys),
            binding.spec,
        )
        if previous_length:
            previous_ref = _store_cache(
                binding.tensor_store,
                tuple(combined_keys[:previous_length]),
                schema_id=_KEY_SCHEMA,
            )
            attention = binding.attention.score(
                AdaCM2AttentionRequest(
                    layer_id=layer_id,
                    previous_key_ref=previous_ref,
                    query_text_ref=query_text_ref,
                    token_count=previous_length,
                    frame_index=frames_seen,
                )
            )
            if not isinstance(attention, AdaCM2AttentionScores):
                raise TypeError(
                    "AdaCM2 attention port must return AdaCM2AttentionScores"
                )
        else:
            attention = AdaCM2AttentionScores((0.0,))

        (
            reduced_keys,
            reduced_values,
            receipt,
        ) = reduce_adacm2_cache(
            tuple(combined_keys),
            tuple(combined_values),
            attention,
            spec=binding.spec,
        )
        key_ref = _store_cache(
            binding.tensor_store,
            reduced_keys,
            schema_id=_KEY_SCHEMA,
        )
        value_ref = _store_cache(
            binding.tensor_store,
            reduced_values,
            schema_id=_VALUE_SCHEMA,
        )
        row = {
            "layer_id": layer_id,
            "key_ref": key_ref.payload(),
            "value_ref": value_ref.payload(),
            "frames_seen": frames_seen + 1,
            "cache_length": len(reduced_keys),
            "reduction_receipt": receipt.payload(),
            "layer_digest": canonical_digest({
                "layer_id": layer_id,
                "key_tensor_digest": key_ref.tensor_digest,
                "value_tensor_digest": value_ref.tensor_digest,
                "frames_seen": frames_seen + 1,
                "receipt_digest": receipt.receipt_digest,
            }),
        }
        layers = [
            item for item in layers if item.get("layer_id") != layer_id
        ]
        layers.append(row)
        layers.sort(key=lambda item: str(item.get("layer_id")))
        frame_index = data.get("frame_index", 0)
        sequence = data.get("sequence", 0)
        if type(frame_index) is not int or frame_index < 0:
            raise ValueError("AdaCM2 frame_index is invalid")
        if type(sequence) is not int or sequence < 0:
            raise ValueError("AdaCM2 sequence is invalid")
        value = {
            "layer_id": layer_id,
            "frames_seen": frames_seen + 1,
            "before_length": receipt.before_length,
            "cache_length": len(reduced_keys),
            "reduction_receipt": receipt.payload(),
            "key_ref": key_ref.payload(),
            "value_ref": value_ref.payload(),
        }
        return ProgramNodeResult(
            value=value,
            state_update={
                "layers": tuple(layers),
                "frame_index": max(frame_index, frames_seen + 1),
                "sequence": sequence + 1,
                "result": value,
            },
            events=({
                "type": "adacm2_layer_cache_reduced",
                "layer_id": layer_id,
                "frames_seen": frames_seen + 1,
                "before_length": receipt.before_length,
                "after_length": receipt.after_length,
                "interpretation": interpretation.value,
                "receipt_digest": receipt.receipt_digest,
            },),
            artifact_refs=(
                key_ref.content.content_sha256,
                value_ref.content.content_sha256,
            ),
        )

    if kind == "adacm2.cache.read":
        layer_id = payload.get("layer_id")
        selected = layers
        if layer_id is not None:
            layer_id = _text(layer_id, "AdaCM2 layer_id")
            selected = [
                row for row in layers if row.get("layer_id") == layer_id
            ]
        value = {
            "layers": tuple(selected),
            "layer_count": len(selected),
            "frame_index": data.get("frame_index", 0),
            "interpretation": interpretation.value,
            "operational_retention_factor": (
                binding.spec.operational_retention_factor
            ),
            "stated_theoretical_retention_factor": (
                binding.spec.stated_theoretical_retention_factor
            ),
        }
        return ProgramNodeResult(
            value=value,
            state_update={"result": value},
            events=({
                "type": "adacm2_cache_read",
                "layer_count": len(selected),
                "interpretation": interpretation.value,
            },),
        )

    if kind == "adacm2.cache.reset":
        value = {"cleared_layer_count": len(layers)}
        return ProgramNodeResult(
            value=value,
            state_update={
                "layers": (),
                "frame_index": 0,
                "result": value,
            },
            events=({
                "type": "adacm2_cache_reset",
                "cleared_layer_count": len(layers),
            },),
        )

    raise ValueError(f"unsupported AdaCM2 memory event: {kind}")


def build_adacm2_memory_program() -> ResearchProgram:
    fidelity = ADACM2_REFERENCE_FIDELITY
    return (
        MemoryProgramBuilder.create(
            program_id="adacm2.cross-modal-kv-memory",
            version="cvpr2025",
            state_schema="adacm2.cross-modal-kv-memory.state.v1",
            entrypoint="dispatch",
        )
        .custom(
            "dispatch",
            "adacm2.memory.dispatch",
            configuration={
                "memory_concerns": (
                    MemoryConcern.WRITE.value,
                    MemoryConcern.RETRIEVAL.value,
                    MemoryConcern.CONSOLIDATION.value,
                    MemoryConcern.RETENTION.value,
                ),
                "alpha": fidelity.alpha,
                "beta": fidelity.beta,
                "cross_modal_score": (
                    fidelity.cross_modal_score_reduction
                ),
                "reduction_scope": fidelity.reduction_scope,
                "paper_eq6_ratio": fidelity.eq6_recent_previous_ratio,
                "paper_eq8_retention": (
                    fidelity.stated_theoretical_retention_formula
                ),
                "paper_internal_inconsistency": (
                    fidelity.eq6_and_eq8_are_jointly_inconsistent
                ),
                "tensor_state": "content-addressed-reference-only",
            },
            next_node="dispatch",
        )
        .build()
    )


ADACM2_MEMORY_PROGRAM = build_adacm2_memory_program()


def adacm2_memory_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "adacm2.memory.dispatch",
            _dispatch,
            canonical_digest({
                "operation": "adacm2.memory.dispatch",
                "paper_revision": "cvpr-2025-camera-ready",
                "implementation_revision": 1,
            }),
        ),
    )


def adacm2_memory_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="adacm2.cross-modal-kv-memory",
        program=ADACM2_MEMORY_PROGRAM,
        operations=adacm2_memory_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=4,
        dependency_identity={
            "paper_revision": "cvpr-2025-camera-ready",
            "paper_semantics_digest": canonical_digest({
                "alpha": 0.1,
                "beta": 0.1,
                "eq6_ratio": "(1-alpha)/alpha",
                "eq8_retention": "alpha+(1-alpha)*beta",
                "internal_inconsistency_preserved": True,
                "implementation_revision": 1,
            }),
        },
    )


__all__ = [
    "ADACM2_MEMORY_PROGRAM",
    "AdaCM2AttentionRequest",
    "AdaCM2AttentionScores",
    "AdaCM2CrossModalAttentionPort",
    "AdaCM2MemoryBinding",
    "AdaCM2ReductionReceipt",
    "AdaCM2ReductionSpec",
    "adacm2_memory_host",
    "adacm2_memory_initial_data",
    "adacm2_memory_operations",
    "adacm2_partition_lengths",
    "build_adacm2_memory_program",
    "reduce_adacm2_cache",
]
