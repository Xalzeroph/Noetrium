from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math

from noetrium_platform.evidence.artifact.content.api import (
    TensorContentRef,
    TensorContentStorePort,
)
from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    MachineJournalPort,
    MachineSnapshotStorePort,
    canonical_digest,
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

from .source import MALMM_AUDITED_COMMIT


Vector = tuple[float, ...]
Frame = tuple[Vector, ...]
CompressionSizes = tuple[tuple[int, ...], ...]
MemoryBank = tuple[Frame, ...]

_MEMORY_BANK_SCHEMA = "ma-lmm.memory-bank.tensor.v1"
_COMPRESSION_SIZE_SCHEMA = "ma-lmm.compression-size.tensor.v1"
_FRAME_SCHEMA = "ma-lmm.frame-embedding.tensor.v1"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _vector(value: object, field_name: str) -> Vector:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a numeric sequence")
    row = tuple(
        _number(item, f"{field_name} component")
        for item in value
    )
    if not row:
        raise ValueError(f"{field_name} must not be empty")
    return row


def _frame(value: object, field_name: str) -> Frame:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a token sequence")
    frame = tuple(
        _vector(item, f"{field_name} token")
        for item in value
    )
    if not frame:
        raise ValueError(f"{field_name} must contain tokens")
    width = len(frame[0])
    if any(len(token) != width for token in frame):
        raise ValueError(f"{field_name} token widths must match")
    return frame


def _frames(value: object, field_name: str) -> MemoryBank:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a frame sequence")
    rows = tuple(_frame(item, field_name) for item in value)
    if not rows:
        return ()
    token_count = len(rows[0])
    width = len(rows[0][0])
    for row in rows:
        if len(row) != token_count:
            raise ValueError(f"{field_name} token counts must match")
        if any(len(token) != width for token in row):
            raise ValueError(f"{field_name} embedding widths must match")
    return rows


def _sizes(value: object, field_name: str) -> CompressionSizes:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a sequence")
    result: list[tuple[int, ...]] = []
    for row in value:
        if isinstance(row, (str, bytes, bytearray)) or not isinstance(
            row,
            Sequence,
        ):
            raise TypeError(f"{field_name} row must be a sequence")
        parsed = tuple(row)
        if any(type(item) is not int or item < 1 for item in parsed):
            raise ValueError(
                f"{field_name} values must be positive integers"
            )
        result.append(parsed)
    return tuple(result)


def _cosine(left: Vector, right: Vector, *, epsilon: float) -> float:
    if len(left) != len(right):
        raise ValueError("MA-LMM cosine vectors must share width")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    denominator = max(left_norm, epsilon) * max(right_norm, epsilon)
    return dot / denominator


@dataclass(frozen=True, slots=True)
class MALMMCompressionReceipt:
    merge_indices: tuple[int, ...]
    before_length: int
    after_length: int
    before_sizes_digest: str
    after_sizes_digest: str
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.merge_indices) is not tuple or any(
            type(value) is not int or value < 0
            for value in self.merge_indices
        ):
            raise TypeError(
                "MA-LMM merge_indices must be non-negative integers"
            )
        if type(self.before_length) is not int or self.before_length < 2:
            raise ValueError(
                "MA-LMM compression requires at least two frames"
            )
        if self.after_length != self.before_length - 1:
            raise ValueError(
                "MA-LMM compression must remove exactly one temporal slot"
            )
        object.__setattr__(
            self,
            "before_sizes_digest",
            require_sha256(
                self.before_sizes_digest,
                "MA-LMM before_sizes_digest",
            ),
        )
        object.__setattr__(
            self,
            "after_sizes_digest",
            require_sha256(
                self.after_sizes_digest,
                "MA-LMM after_sizes_digest",
            ),
        )
        object.__setattr__(
            self,
            "receipt_digest",
            canonical_digest({
                "merge_indices": self.merge_indices,
                "before_length": self.before_length,
                "after_length": self.after_length,
                "before_sizes_digest": self.before_sizes_digest,
                "after_sizes_digest": self.after_sizes_digest,
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "merge_indices": self.merge_indices,
            "before_length": self.before_length,
            "after_length": self.after_length,
            "before_sizes_digest": self.before_sizes_digest,
            "after_sizes_digest": self.after_sizes_digest,
            "receipt_digest": self.receipt_digest,
        }


def compress_memory_bank(
    frames: MemoryBank,
    compression_sizes: CompressionSizes,
    *,
    epsilon: float = 1e-8,
) -> tuple[MemoryBank, CompressionSizes, MALMMCompressionReceipt]:
    """Paper-era MA-LMM adjacent-similarity compression for one batch item.

    The official tensor implementation chooses the maximally similar adjacent
    temporal pair independently for every token position. The later frame in
    that pair is merged into the earlier frame by compression-size-weighted
    averaging. Other temporal positions are retained.
    """

    if type(frames) is not tuple or len(frames) < 2:
        raise ValueError(
            "MA-LMM compression requires at least two frames"
        )
    parsed_frames = _frames(frames, "MA-LMM frames")
    parsed_sizes = _sizes(
        compression_sizes,
        "MA-LMM compression_sizes",
    )
    if len(parsed_sizes) != len(parsed_frames):
        raise ValueError(
            "MA-LMM compression sizes must align with frames"
        )
    token_count = len(parsed_frames[0])
    if any(len(row) != token_count for row in parsed_sizes):
        raise ValueError(
            "MA-LMM compression sizes must align with tokens"
        )
    if (
        isinstance(epsilon, bool)
        or not isinstance(epsilon, (int, float))
        or epsilon <= 0
    ):
        raise ValueError("MA-LMM cosine epsilon must be positive")
    eps = float(epsilon)

    merge_indices: list[int] = []
    for token_index in range(token_count):
        similarities = tuple(
            _cosine(
                parsed_frames[index][token_index],
                parsed_frames[index + 1][token_index],
                epsilon=eps,
            )
            for index in range(len(parsed_frames) - 1)
        )
        # torch.max returns the first index on ties.
        merge_index = max(
            range(len(similarities)),
            key=lambda index: (similarities[index], -index),
        )
        merge_indices.append(merge_index)

    output_length = len(parsed_frames) - 1
    out_frames: list[list[Vector]] = [
        [() for _ in range(token_count)]  # type: ignore[list-item]
        for _ in range(output_length)
    ]
    out_sizes: list[list[int]] = [
        [0 for _ in range(token_count)]
        for _ in range(output_length)
    ]

    for token_index, merge_index in enumerate(merge_indices):
        source_index = merge_index + 1
        for output_index in range(output_length):
            original_index = (
                output_index
                if output_index <= merge_index
                else output_index + 1
            )
            vector = parsed_frames[original_index][token_index]
            weight = parsed_sizes[original_index][token_index]

            if output_index == merge_index:
                source_vector = parsed_frames[source_index][token_index]
                source_weight = parsed_sizes[source_index][token_index]
                total_weight = weight + source_weight
                vector = tuple(
                    (
                        component * weight
                        + source_component * source_weight
                    )
                    / total_weight
                    for component, source_component
                    in zip(vector, source_vector)
                )
                weight = total_weight

            out_frames[output_index][token_index] = vector
            out_sizes[output_index][token_index] = weight

    compressed_frames = tuple(
        tuple(token for token in frame)
        for frame in out_frames
    )
    compressed_sizes = tuple(
        tuple(row) for row in out_sizes
    )
    receipt = MALMMCompressionReceipt(
        merge_indices=tuple(merge_indices),
        before_length=len(parsed_frames),
        after_length=len(compressed_frames),
        before_sizes_digest=canonical_digest(parsed_sizes),
        after_sizes_digest=canonical_digest(compressed_sizes),
    )
    return compressed_frames, compressed_sizes, receipt


@dataclass(frozen=True, slots=True)
class MALMMMemoryBinding:
    tensor_store: TensorContentStorePort
    cosine_epsilon: float = 1e-8
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.tensor_store, TensorContentStorePort):
            raise TypeError(
                "MA-LMM memory requires TensorContentStorePort"
            )
        tensor_store_digest = require_sha256(
            self.tensor_store.identity_digest,
            "MA-LMM tensor store identity_digest",
        )
        if (
            isinstance(self.cosine_epsilon, bool)
            or not isinstance(self.cosine_epsilon, (int, float))
            or self.cosine_epsilon <= 0
        ):
            raise ValueError(
                "MA-LMM cosine_epsilon must be positive"
            )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "source_commit": MALMM_AUDITED_COMMIT,
                "compression": (
                    "per-token-adjacent-cosine-weighted-average"
                ),
                "cosine_epsilon": float(self.cosine_epsilon),
                "tensor_store_identity_digest": tensor_store_digest,
                "implementation_revision": 2,
            }),
        )


def ma_lmm_memory_initial_data(
    *,
    memory_bank_length: int,
    num_frames: int,
) -> JsonObject:
    if type(memory_bank_length) is not int or memory_bank_length < 1:
        raise ValueError(
            "MA-LMM memory_bank_length must be positive"
        )
    if type(num_frames) is not int or num_frames < 1:
        raise ValueError("MA-LMM num_frames must be positive")
    return {
        "source_commit": MALMM_AUDITED_COMMIT,
        "memory_bank_length": memory_bank_length,
        "num_frames": num_frames,
        "banks": (),
        "sequence": 0,
        "result": None,
    }


def _data(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.data)
    if not isinstance(decoded, dict):
        raise TypeError(
            "MA-LMM memory state must be an object"
        )
    if decoded.get("source_commit") != MALMM_AUDITED_COMMIT:
        raise ValueError("MA-LMM source identity drifted")
    return decoded


def _payload(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.payload)
    if not isinstance(decoded, dict):
        raise TypeError(
            "MA-LMM memory payload must be an object"
        )
    event = decoded.get("event")
    if not isinstance(event, Mapping):
        raise TypeError(
            "MA-LMM memory requires event envelope"
        )
    event_decoded = thaw_json(event)
    if not isinstance(event_decoded, dict):
        raise TypeError(
            "MA-LMM memory event must decode to an object"
        )
    return event_decoded


def _banks(data: Mapping[str, object]) -> list[dict[str, object]]:
    value = thaw_json(data.get("banks", ()))
    if not isinstance(value, (tuple, list)):
        raise TypeError("MA-LMM banks must be a sequence")
    rows: list[dict[str, object]] = []
    for row in value:
        if not isinstance(row, dict):
            raise TypeError(
                "MA-LMM bank row must be an object"
            )
        rows.append(row)
    return rows


def _tensor_ref(
    value: object,
    field_name: str,
) -> TensorContentRef:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a tensor reference")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(
            f"{field_name} must decode to an object"
        )
    return TensorContentRef.from_payload(decoded)


def _verify_tensor(
    store: TensorContentStorePort,
    ref: TensorContentRef,
    *,
    field_name: str,
) -> None:
    if not store.verify(ref):
        raise ValueError(
            f"{field_name} failed immutable tensor verification"
        )


def _materialize_bank(
    store: TensorContentStorePort,
    ref: TensorContentRef,
) -> MemoryBank:
    _verify_tensor(
        store,
        ref,
        field_name="MA-LMM memory bank",
    )
    return _frames(
        store.get(ref),
        "MA-LMM materialized memory bank",
    )


def _materialize_sizes(
    store: TensorContentStorePort,
    ref: TensorContentRef,
) -> CompressionSizes:
    _verify_tensor(
        store,
        ref,
        field_name="MA-LMM compression sizes",
    )
    return _sizes(
        store.get(ref),
        "MA-LMM materialized compression sizes",
    )


def _store_bank(
    store: TensorContentStorePort,
    frames: MemoryBank,
) -> TensorContentRef:
    ref = store.put(
        frames,
        schema_id=_MEMORY_BANK_SCHEMA,
    )
    if not isinstance(ref, TensorContentRef):
        raise TypeError(
            "MA-LMM tensor store must return TensorContentRef"
        )
    expected_shape = (
        len(frames),
        len(frames[0]),
        len(frames[0][0]),
    )
    if ref.shape != expected_shape:
        raise ValueError(
            "MA-LMM memory-bank tensor shape drifted"
        )
    return ref


def _store_sizes(
    store: TensorContentStorePort,
    sizes: CompressionSizes,
) -> TensorContentRef:
    ref = store.put(
        sizes,
        schema_id=_COMPRESSION_SIZE_SCHEMA,
    )
    if not isinstance(ref, TensorContentRef):
        raise TypeError(
            "MA-LMM tensor store must return TensorContentRef"
        )
    expected_shape = (
        len(sizes),
        len(sizes[0]),
    )
    if ref.shape != expected_shape:
        raise ValueError(
            "MA-LMM compression-size tensor shape drifted"
        )
    return ref


def _materialize_frame(
    store: TensorContentStorePort,
    ref: TensorContentRef,
) -> Frame:
    _verify_tensor(
        store,
        ref,
        field_name="MA-LMM input frame",
    )
    frame = _frame(
        store.get(ref),
        "MA-LMM materialized input frame",
    )
    if ref.shape != (len(frame), len(frame[0])):
        raise ValueError(
            "MA-LMM input frame tensor shape drifted"
        )
    return frame


def _bank_digest(bank: Mapping[str, object]) -> str:
    return canonical_digest(bank)


def _dispatch(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, MALMMMemoryBinding):
        raise TypeError(
            "MA-LMM memory requires MALMMMemoryBinding"
        )
    data = _data(request)
    envelope = _payload(request)
    kind = _text(
        envelope.get("kind"),
        "MA-LMM event kind",
    )
    payload = envelope.get("payload", {})
    if not isinstance(payload, Mapping):
        raise TypeError(
            "MA-LMM event payload must be an object"
        )
    payload = thaw_json(payload)
    if not isinstance(payload, dict):
        raise TypeError(
            "MA-LMM event payload must decode to an object"
        )

    banks = _banks(data)
    memory_bank_length = data.get("memory_bank_length")
    num_frames = data.get("num_frames")
    if (
        type(memory_bank_length) is not int
        or memory_bank_length < 1
    ):
        raise ValueError(
            "MA-LMM memory_bank_length state is invalid"
        )
    if type(num_frames) is not int or num_frames < 1:
        raise ValueError(
            "MA-LMM num_frames state is invalid"
        )

    if kind == "ma_lmm.memory.append":
        bank_id = _text(
            payload.get("bank_id"),
            "MA-LMM bank_id",
        )
        bank_kind = _text(
            payload.get("bank_kind"),
            "MA-LMM bank_kind",
        )
        if bank_kind not in {"visual", "query"}:
            raise ValueError(
                "MA-LMM bank_kind must be visual or query"
            )
        frame_ref = _tensor_ref(
            payload.get("frame_ref"),
            "MA-LMM frame_ref",
        )
        if frame_ref.schema_id != _FRAME_SCHEMA:
            raise ValueError(
                "MA-LMM frame tensor schema drifted"
            )
        frame = _materialize_frame(
            binding.tensor_store,
            frame_ref,
        )
        final = payload.get("final", False)
        if type(final) is not bool:
            raise TypeError(
                "MA-LMM final flag must be boolean"
            )

        existing = next(
            (
                row
                for row in banks
                if row.get("bank_id") == bank_id
            ),
            None,
        )
        if existing is None:
            frames: MemoryBank = ()
            sizes: CompressionSizes = ()
            seen_frames = 0
        else:
            if existing.get("bank_kind") != bank_kind:
                raise ValueError(
                    "MA-LMM bank kind drifted"
                )
            bank_ref = _tensor_ref(
                existing.get("memory_ref"),
                "MA-LMM memory_ref",
            )
            sizes_ref = _tensor_ref(
                existing.get("compression_sizes_ref"),
                "MA-LMM compression_sizes_ref",
            )
            frames = _materialize_bank(
                binding.tensor_store,
                bank_ref,
            )
            sizes = _materialize_sizes(
                binding.tensor_store,
                sizes_ref,
            )
            seen_frames = existing.get("seen_frames", 0)
            if (
                type(seen_frames) is not int
                or seen_frames < 0
            ):
                raise ValueError(
                    "MA-LMM seen_frames is invalid"
                )

        if seen_frames >= num_frames:
            raise ValueError(
                "MA-LMM received more frames than configured"
            )
        if frames:
            if len(frame) != len(frames[0]):
                raise ValueError(
                    "MA-LMM appended token count drifted"
                )
            if len(frame[0]) != len(frames[0][0]):
                raise ValueError(
                    "MA-LMM appended embedding width drifted"
                )

        next_frames = (*frames, frame)
        next_sizes: CompressionSizes = (
            *sizes,
            tuple(1 for _ in frame),
        )
        next_seen = seen_frames + 1
        should_finish = final or next_seen == num_frames
        if final and next_seen != num_frames:
            raise ValueError(
                "MA-LMM final frame must match configured num_frames"
            )

        compression: MALMMCompressionReceipt | None = None
        if not should_finish and len(next_frames) > memory_bank_length:
            (
                next_frames,
                next_sizes,
                compression,
            ) = compress_memory_bank(
                tuple(next_frames),
                next_sizes,
                epsilon=binding.cosine_epsilon,
            )

        memory_ref = _store_bank(
            binding.tensor_store,
            tuple(next_frames),
        )
        compression_sizes_ref = _store_sizes(
            binding.tensor_store,
            next_sizes,
        )

        if should_finish:
            banks = [
                row
                for row in banks
                if row.get("bank_id") != bank_id
            ]
        else:
            row = {
                "bank_id": bank_id,
                "bank_kind": bank_kind,
                "seen_frames": next_seen,
                "memory_ref": memory_ref.payload(),
                "compression_sizes_ref": (
                    compression_sizes_ref.payload()
                ),
                "bank_digest": canonical_digest({
                    "bank_id": bank_id,
                    "bank_kind": bank_kind,
                    "seen_frames": next_seen,
                    "memory_tensor_digest": (
                        memory_ref.tensor_digest
                    ),
                    "compression_sizes_tensor_digest": (
                        compression_sizes_ref.tensor_digest
                    ),
                }),
            }
            banks = [
                item
                for item in banks
                if item.get("bank_id") != bank_id
            ]
            banks.append(row)
            banks.sort(
                key=lambda item: str(item.get("bank_id"))
            )

        sequence = data.get("sequence", 0)
        if type(sequence) is not int or sequence < 0:
            raise ValueError(
                "MA-LMM memory sequence is invalid"
            )
        result = {
            "bank_id": bank_id,
            "bank_kind": bank_kind,
            "seen_frames": next_seen,
            "active": not should_finish,
            "active_length": (
                0 if should_finish else len(next_frames)
            ),
            "compression_receipt": (
                None
                if compression is None
                else compression.payload()
            ),
            "memory_ref": memory_ref.payload(),
            "compression_sizes_ref": (
                compression_sizes_ref.payload()
            ),
            "state_digest": canonical_digest(tuple(banks)),
        }
        return ProgramNodeResult(
            value=result,
            state_update={
                "banks": tuple(banks),
                "sequence": sequence + 1,
                "result": result,
            },
            events=({
                "type": "ma_lmm_memory_frame_appended",
                "bank_id": bank_id,
                "bank_kind": bank_kind,
                "seen_frames": next_seen,
                "active": not should_finish,
                "compressed": compression is not None,
                "input_frame_tensor_digest": (
                    frame_ref.tensor_digest
                ),
                "memory_tensor_digest": (
                    memory_ref.tensor_digest
                ),
                "compression_sizes_tensor_digest": (
                    compression_sizes_ref.tensor_digest
                ),
                "compression_receipt_digest": (
                    None
                    if compression is None
                    else compression.receipt_digest
                ),
                "state_digest": result["state_digest"],
            },),
        )

    if kind == "ma_lmm.memory.read":
        bank_id = _text(
            payload.get("bank_id"),
            "MA-LMM bank_id",
        )
        bank = next(
            (
                row
                for row in banks
                if row.get("bank_id") == bank_id
            ),
            None,
        )
        if bank is None:
            result = {
                "bank_id": bank_id,
                "active": False,
                "memory_ref": None,
                "compression_sizes_ref": None,
                "state_digest": canonical_digest(
                    tuple(banks)
                ),
            }
        else:
            memory_ref = _tensor_ref(
                bank.get("memory_ref"),
                "MA-LMM memory_ref",
            )
            sizes_ref = _tensor_ref(
                bank.get("compression_sizes_ref"),
                "MA-LMM compression_sizes_ref",
            )
            _verify_tensor(
                binding.tensor_store,
                memory_ref,
                field_name="MA-LMM memory bank",
            )
            _verify_tensor(
                binding.tensor_store,
                sizes_ref,
                field_name="MA-LMM compression sizes",
            )
            result = {
                "bank_id": bank_id,
                "bank_kind": bank.get("bank_kind"),
                "active": True,
                "seen_frames": bank.get("seen_frames"),
                "memory_ref": memory_ref.payload(),
                "compression_sizes_ref": (
                    sizes_ref.payload()
                ),
                "attention_role": (
                    "prepend_key_value"
                    if bank.get("bank_kind") == "query"
                    else "encoder_history"
                ),
                "bank_digest": bank.get(
                    "bank_digest",
                    _bank_digest(bank),
                ),
                "state_digest": canonical_digest(
                    tuple(banks)
                ),
            }
        return ProgramNodeResult(
            value=result,
            state_update={"result": result},
            events=({
                "type": "ma_lmm_memory_read",
                "bank_id": bank_id,
                "active": result["active"],
                "memory_tensor_digest": (
                    None
                    if result.get("memory_ref") is None
                    else result["memory_ref"][
                        "tensor_digest"
                    ]
                ),
                "state_digest": result["state_digest"],
            },),
        )

    if kind == "ma_lmm.memory.reset":
        bank_id = payload.get("bank_id")
        if bank_id is None:
            removed = tuple(
                str(row.get("bank_id"))
                for row in banks
            )
            banks = []
        else:
            bank_id = _text(
                bank_id,
                "MA-LMM bank_id",
            )
            removed = tuple(
                str(row.get("bank_id"))
                for row in banks
                if row.get("bank_id") == bank_id
            )
            banks = [
                row
                for row in banks
                if row.get("bank_id") != bank_id
            ]
        result = {
            "removed_bank_ids": removed,
            "state_digest": canonical_digest(tuple(banks)),
        }
        return ProgramNodeResult(
            value=result,
            state_update={
                "banks": tuple(banks),
                "result": result,
            },
            events=({
                "type": "ma_lmm_memory_reset",
                "removed_bank_ids": removed,
                "state_digest": result["state_digest"],
            },),
        )

    raise ValueError(
        f"unsupported MA-LMM memory event: {kind}"
    )


def build_ma_lmm_memory_program() -> ResearchProgram:
    return (
        MemoryProgramBuilder.create(
            program_id="ma-lmm.multimodal-memory",
            version=MALMM_AUDITED_COMMIT[:12],
            state_schema="ma-lmm.multimodal-memory.state.v2",
            entrypoint="dispatch",
        )
        .custom(
            "dispatch",
            "ma_lmm.memory.dispatch",
            configuration={
                "memory_concerns": (
                    MemoryConcern.WRITE.value,
                    MemoryConcern.RETRIEVAL.value,
                    MemoryConcern.CONSOLIDATION.value,
                    MemoryConcern.RETENTION.value,
                ),
                "source_commit": MALMM_AUDITED_COMMIT,
                "compression": (
                    "per-token-adjacent-cosine-"
                    "weighted-average"
                ),
                "tensor_state": (
                    "content-addressed-reference-only"
                ),
            },
            next_node="dispatch",
        )
        .build()
    )


MA_LMM_MEMORY_PROGRAM = build_ma_lmm_memory_program()


def ma_lmm_memory_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "ma_lmm.memory.dispatch",
            _dispatch,
            canonical_digest({
                "operation": "ma_lmm.memory.dispatch",
                "source_commit": MALMM_AUDITED_COMMIT,
                "implementation_revision": 2,
            }),
        ),
    )


def ma_lmm_memory_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="ma-lmm.multimodal-memory",
        program=MA_LMM_MEMORY_PROGRAM,
        operations=ma_lmm_memory_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=4,
        dependency_identity={
            "source_commit": MALMM_AUDITED_COMMIT,
            "compression_semantics": canonical_digest({
                "pair_selection": (
                    "per-token-adjacent-cosine-argmax"
                ),
                "merge": (
                    "compression-size-weighted-average"
                ),
                "tensor_state": (
                    "content-addressed-reference-only"
                ),
                "implementation_revision": 2,
            }),
        },
    )


__all__ = [
    "MA_LMM_MEMORY_PROGRAM",
    "MALMMCompressionReceipt",
    "MALMMMemoryBinding",
    "build_ma_lmm_memory_program",
    "compress_memory_bank",
    "ma_lmm_memory_host",
    "ma_lmm_memory_initial_data",
    "ma_lmm_memory_operations",
]
