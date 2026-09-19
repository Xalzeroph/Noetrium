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

from .fidelity import MOVIECHAT_REFERENCE_FIDELITY
from .source import MOVIECHAT_AUDITED_COMMIT


Vector = tuple[float, ...]
Frame = tuple[Vector, ...]
FrameSequence = tuple[Frame, ...]

_FRAGMENT_SCHEMA = "moviechat.fragment-frame-embeddings.tensor.v1"
_FRAME_SCHEMA = "moviechat.frame-embedding.tensor.v1"
_SHORT_SCHEMA = "moviechat.short-memory.tensor.v1"
_TEMP_SHORT_SCHEMA = "moviechat.temp-short-memory.tensor.v1"
_LONG_SCHEMA = "moviechat.long-memory.tensor.v1"
_READOUT_SCHEMA = "moviechat.memory-readout.tensor.v1"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _vector(value: object, field_name: str) -> Vector:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a numeric sequence")
    row = tuple(_number(item, field_name) for item in value)
    if not row:
        raise ValueError(f"{field_name} must not be empty")
    return row


def _frame(value: object, field_name: str) -> Frame:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a token sequence")
    row = tuple(_vector(item, field_name) for item in value)
    if not row:
        raise ValueError(f"{field_name} must contain tokens")
    width = len(row[0])
    if any(len(token) != width for token in row):
        raise ValueError(f"{field_name} token widths must match")
    return row


def _frames(value: object, field_name: str) -> FrameSequence:
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
    if any(
        len(frame) != token_count
        or any(len(token) != width for token in frame)
        for frame in rows
    ):
        raise ValueError(f"{field_name} frame shapes must match")
    return rows


def _flat(frame: Frame) -> Vector:
    return tuple(value for token in frame for value in token)


def _mean_pairwise_token_dot(left: Frame, right: Frame) -> float:
    if len(left) != len(right) or len(left[0]) != len(right[0]):
        raise ValueError(
            "MovieChat short-memory frame shapes must match"
        )
    total = 0.0
    count = 0
    for left_token in left:
        for right_token in right:
            total += sum(
                a * b for a, b in zip(left_token, right_token)
            )
            count += 1
    if count == 0:
        raise ValueError(
            "MovieChat short-memory similarity has no token pairs"
        )
    return total / count


def _cosine_distance(left: Frame, right: Frame) -> float:
    a = _flat(left)
    b = _flat(right)
    if len(a) != len(b):
        raise ValueError(
            "MovieChat long-memory frame widths must match"
        )
    dot = sum(x * y for x, y in zip(a, b))
    left_norm = math.sqrt(sum(x * x for x in a))
    right_norm = math.sqrt(sum(y * y for y in b))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError(
            "MovieChat executable cosine-distance path is undefined "
            "for zero-norm frames"
        )
    return 1.0 - dot / (left_norm * right_norm)


def _mean_frame(left: Frame, right: Frame) -> Frame:
    if len(left) != len(right) or len(left[0]) != len(right[0]):
        raise ValueError("MovieChat merge frame shapes must match")
    return tuple(
        tuple(
            (a + b) / 2.0
            for a, b in zip(left_token, right_token)
        )
        for left_token, right_token in zip(left, right)
    )


@dataclass(frozen=True, slots=True)
class MovieChatMergeReceipt:
    memory_kind: str
    pair_index: int
    selection_metric: str
    selection_value: float
    before_length: int
    after_length: int
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if self.memory_kind not in {"short", "long"}:
            raise ValueError(
                "MovieChat memory_kind must be short or long"
            )
        if type(self.pair_index) is not int or self.pair_index < 0:
            raise ValueError(
                "MovieChat pair_index must be non-negative"
            )
        if self.after_length != self.before_length - 1:
            raise ValueError(
                "MovieChat merge must remove one frame"
            )
        object.__setattr__(
            self,
            "receipt_digest",
            canonical_digest({
                "memory_kind": self.memory_kind,
                "pair_index": self.pair_index,
                "selection_metric": self.selection_metric,
                "selection_value": self.selection_value,
                "before_length": self.before_length,
                "after_length": self.after_length,
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "memory_kind": self.memory_kind,
            "pair_index": self.pair_index,
            "selection_metric": self.selection_metric,
            "selection_value": self.selection_value,
            "before_length": self.before_length,
            "after_length": self.after_length,
            "receipt_digest": self.receipt_digest,
        }


def consolidate_short_memory(
    frames: FrameSequence,
    *,
    target_length: int,
) -> tuple[FrameSequence, tuple[MovieChatMergeReceipt, ...]]:
    if type(target_length) is not int or target_length < 1:
        raise ValueError(
            "MovieChat short target_length must be positive"
        )
    rows = list(_frames(frames, "MovieChat short memory"))
    receipts: list[MovieChatMergeReceipt] = []
    while len(rows) > target_length:
        scores = tuple(
            _mean_pairwise_token_dot(
                rows[index],
                rows[index + 1],
            )
            for index in range(len(rows) - 1)
        )
        pair_index = max(
            range(len(scores)),
            key=lambda index: (scores[index], -index),
        )
        before = len(rows)
        rows[pair_index] = _mean_frame(
            rows[pair_index],
            rows[pair_index + 1],
        )
        del rows[pair_index + 1]
        receipts.append(
            MovieChatMergeReceipt(
                memory_kind="short",
                pair_index=pair_index,
                selection_metric=(
                    "mean_pairwise_token_dot_product"
                ),
                selection_value=scores[pair_index],
                before_length=before,
                after_length=len(rows),
            )
        )
    return tuple(rows), tuple(receipts)


def consolidate_direct_long_memory(
    frames: FrameSequence,
    *,
    target_length: int,
) -> tuple[FrameSequence, tuple[MovieChatMergeReceipt, ...]]:
    """Reproduce the paper-era source's direct LTM path exactly.

    The source imports scipy.spatial.distance.cosine and chooses max(). This is
    cosine distance, so this executable lane selects the most distant adjacent
    pair, despite the paper describing top cosine similarity.
    """

    if type(target_length) is not int or target_length < 1:
        raise ValueError(
            "MovieChat long target_length must be positive"
        )
    rows = list(_frames(frames, "MovieChat long memory"))
    receipts: list[MovieChatMergeReceipt] = []
    while len(rows) > target_length:
        distances = tuple(
            _cosine_distance(
                rows[index],
                rows[index + 1],
            )
            for index in range(len(rows) - 1)
        )
        pair_index = max(
            range(len(distances)),
            key=lambda index: (distances[index], -index),
        )
        before = len(rows)
        rows[pair_index] = _mean_frame(
            rows[pair_index],
            rows[pair_index + 1],
        )
        del rows[pair_index + 1]
        receipts.append(
            MovieChatMergeReceipt(
                memory_kind="long",
                pair_index=pair_index,
                selection_metric="scipy_cosine_distance",
                selection_value=distances[pair_index],
                before_length=before,
                after_length=len(rows),
            )
        )
    return tuple(rows), tuple(receipts)


def _tensor_ref(
    value: object,
    field_name: str,
) -> TensorContentRef:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a tensor reference")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to an object")
    return TensorContentRef.from_payload(decoded)


def _optional_ref(
    value: object,
    field_name: str,
) -> TensorContentRef | None:
    if value is None:
        return None
    return _tensor_ref(value, field_name)


def _verify_ref(
    store: TensorContentStorePort,
    ref: TensorContentRef,
    *,
    schema_id: str,
    field_name: str,
) -> None:
    if ref.schema_id != schema_id:
        raise ValueError(f"{field_name} tensor schema drifted")
    if not store.verify(ref):
        raise ValueError(
            f"{field_name} failed immutable tensor verification"
        )


def _materialize_frames(
    store: TensorContentStorePort,
    ref: TensorContentRef | None,
    *,
    schema_id: str,
    field_name: str,
) -> FrameSequence:
    if ref is None:
        return ()
    _verify_ref(
        store,
        ref,
        schema_id=schema_id,
        field_name=field_name,
    )
    frames = _frames(store.get(ref), field_name)
    expected = (
        len(frames),
        len(frames[0]),
        len(frames[0][0]),
    )
    if ref.shape != expected:
        raise ValueError(f"{field_name} tensor shape drifted")
    return frames


def _materialize_frame(
    store: TensorContentStorePort,
    ref: TensorContentRef,
    *,
    schema_id: str,
    field_name: str,
) -> Frame:
    _verify_ref(
        store,
        ref,
        schema_id=schema_id,
        field_name=field_name,
    )
    frame = _frame(store.get(ref), field_name)
    if ref.shape != (len(frame), len(frame[0])):
        raise ValueError(f"{field_name} tensor shape drifted")
    return frame


def _store_frames(
    store: TensorContentStorePort,
    frames: FrameSequence,
    *,
    schema_id: str,
) -> TensorContentRef | None:
    if not frames:
        return None
    ref = store.put(frames, schema_id=schema_id)
    if not isinstance(ref, TensorContentRef):
        raise TypeError(
            "MovieChat tensor store must return TensorContentRef"
        )
    expected = (
        len(frames),
        len(frames[0]),
        len(frames[0][0]),
    )
    if ref.shape != expected:
        raise ValueError(
            "MovieChat stored frame-sequence shape drifted"
        )
    return ref


def _ref_payload(ref: TensorContentRef | None) -> JsonObject | None:
    return None if ref is None else ref.payload()


def _ref_digest(ref: TensorContentRef | None) -> str | None:
    return None if ref is None else ref.tensor_digest


def _state_digest(
    *,
    short_ref: TensorContentRef | None,
    temp_short_ref: TensorContentRef | None,
    long_ref: TensorContentRef | None,
) -> str:
    return canonical_digest({
        "short_tensor_digest": _ref_digest(short_ref),
        "temp_short_tensor_digest": _ref_digest(temp_short_ref),
        "long_tensor_digest": _ref_digest(long_ref),
    })


@dataclass(frozen=True, slots=True)
class MovieChatMemoryBinding:
    tensor_store: TensorContentStorePort
    executable_semantics: str = "paper-era-source"
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.tensor_store, TensorContentStorePort):
            raise TypeError(
                "MovieChat memory requires TensorContentStorePort"
            )
        tensor_store_digest = require_sha256(
            self.tensor_store.identity_digest,
            "MovieChat tensor store identity_digest",
        )
        if self.executable_semantics != "paper-era-source":
            raise ValueError(
                "MovieChat binding reproduces only paper-era source"
            )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "source_commit": MOVIECHAT_AUDITED_COMMIT,
                "short_similarity": (
                    MOVIECHAT_REFERENCE_FIDELITY.short_similarity
                ),
                "short_merge": (
                    MOVIECHAT_REFERENCE_FIDELITY.short_merge
                ),
                "direct_long_similarity": (
                    MOVIECHAT_REFERENCE_FIDELITY
                    .direct_long_similarity
                ),
                "direct_long_pair_selection": (
                    MOVIECHAT_REFERENCE_FIDELITY
                    .direct_long_pair_selection
                ),
                "tensor_store_identity_digest": tensor_store_digest,
                "implementation_revision": 2,
            }),
        )


def moviechat_memory_initial_data() -> JsonObject:
    fidelity = MOVIECHAT_REFERENCE_FIDELITY
    return {
        "source_commit": MOVIECHAT_AUDITED_COMMIT,
        "short_memory_length": fidelity.short_memory_length,
        "short_memory_merge": fidelity.short_memory_merge,
        "long_memory_length": fidelity.long_memory_length,
        "position_capacity": fidelity.position_capacity,
        "short_memory_ref": None,
        "temp_short_memory_ref": None,
        "long_memory_ref": None,
        "sequence": 0,
        "result": None,
    }


def _data(request: ProgramNodeRequest) -> dict[str, object]:
    value = thaw_json(request.data)
    if not isinstance(value, dict):
        raise TypeError("MovieChat memory state must be an object")
    if value.get("source_commit") != MOVIECHAT_AUDITED_COMMIT:
        raise ValueError("MovieChat source identity drifted")
    return value


def _event(
    request: ProgramNodeRequest,
) -> tuple[str, dict[str, object]]:
    value = thaw_json(request.payload)
    if not isinstance(value, dict):
        raise TypeError("MovieChat payload must be an object")
    event = value.get("event")
    if not isinstance(event, dict):
        raise TypeError(
            "MovieChat memory requires event envelope"
        )
    kind = _text(event.get("kind"), "MovieChat event kind")
    payload = event.get("payload", {})
    if not isinstance(payload, dict):
        raise TypeError(
            "MovieChat event payload must be an object"
        )
    return kind, payload


def _dispatch(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, MovieChatMemoryBinding):
        raise TypeError(
            "MovieChat memory requires MovieChatMemoryBinding"
        )
    data = _data(request)
    kind, payload = _event(request)

    short_limit = data.get("short_memory_length")
    short_merge = data.get("short_memory_merge")
    long_limit = data.get("long_memory_length")
    position_capacity = data.get("position_capacity")
    for name, value in (
        ("short_memory_length", short_limit),
        ("short_memory_merge", short_merge),
        ("long_memory_length", long_limit),
        ("position_capacity", position_capacity),
    ):
        if type(value) is not int or value < 1:
            raise ValueError(
                f"MovieChat {name} state is invalid"
            )

    short_ref = _optional_ref(
        data.get("short_memory_ref"),
        "MovieChat short_memory_ref",
    )
    temp_short_ref = _optional_ref(
        data.get("temp_short_memory_ref"),
        "MovieChat temp_short_memory_ref",
    )
    long_ref = _optional_ref(
        data.get("long_memory_ref"),
        "MovieChat long_memory_ref",
    )
    short = list(
        _materialize_frames(
            binding.tensor_store,
            short_ref,
            schema_id=_SHORT_SCHEMA,
            field_name="MovieChat short memory",
        )
    )
    temp_short = list(
        _materialize_frames(
            binding.tensor_store,
            temp_short_ref,
            schema_id=_TEMP_SHORT_SCHEMA,
            field_name="MovieChat temp short memory",
        )
    )
    long = list(
        _materialize_frames(
            binding.tensor_store,
            long_ref,
            schema_id=_LONG_SCHEMA,
            field_name="MovieChat long memory",
        )
    )

    if kind == "moviechat.fragment.commit":
        fragment_ref = _tensor_ref(
            payload.get("frames_ref"),
            "MovieChat fragment frames_ref",
        )
        fragment = _materialize_frames(
            binding.tensor_store,
            fragment_ref,
            schema_id=_FRAGMENT_SCHEMA,
            field_name="MovieChat fragment frames",
        )
        if not fragment:
            raise ValueError(
                "MovieChat fragment must contain frames"
            )
        if long:
            expected = (len(long[0]), len(long[0][0]))
        elif short:
            expected = (len(short[0]), len(short[0][0]))
        else:
            expected = (
                len(fragment[0]),
                len(fragment[0][0]),
            )
        for frame in fragment:
            if (len(frame), len(frame[0])) != expected:
                raise ValueError(
                    "MovieChat fragment frame shape drifted"
                )
            if len(short) == short_limit:
                short.pop(0)
            short.append(frame)

        temp_short = list(short)
        compressed, receipts = consolidate_short_memory(
            tuple(short),
            target_length=short_merge,
        )
        long.extend(compressed)
        short = []

        short_ref = None
        temp_short_ref = _store_frames(
            binding.tensor_store,
            tuple(temp_short),
            schema_id=_TEMP_SHORT_SCHEMA,
        )
        long_ref = _store_frames(
            binding.tensor_store,
            tuple(long),
            schema_id=_LONG_SCHEMA,
        )

        sequence = data.get("sequence", 0)
        if type(sequence) is not int or sequence < 0:
            raise ValueError(
                "MovieChat sequence is invalid"
            )
        state_digest = _state_digest(
            short_ref=short_ref,
            temp_short_ref=temp_short_ref,
            long_ref=long_ref,
        )
        result = {
            "fragment_frame_count": len(fragment),
            "input_fragment_tensor_digest": (
                fragment_ref.tensor_digest
            ),
            "temp_short_length": len(temp_short),
            "consolidated_short_length": len(compressed),
            "long_memory_length": len(long),
            "short_merge_receipts": tuple(
                receipt.payload() for receipt in receipts
            ),
            "temp_short_memory_ref": _ref_payload(
                temp_short_ref
            ),
            "long_memory_ref": _ref_payload(long_ref),
            "state_digest": state_digest,
        }
        return ProgramNodeResult(
            value=result,
            state_update={
                "short_memory_ref": None,
                "temp_short_memory_ref": _ref_payload(
                    temp_short_ref
                ),
                "long_memory_ref": _ref_payload(long_ref),
                "sequence": sequence + 1,
                "result": result,
            },
            events=({
                "type": "moviechat_fragment_committed",
                "fragment_frame_count": len(fragment),
                "input_fragment_tensor_digest": (
                    fragment_ref.tensor_digest
                ),
                "temp_short_tensor_digest": _ref_digest(
                    temp_short_ref
                ),
                "long_tensor_digest": _ref_digest(long_ref),
                "merge_receipt_digests": tuple(
                    receipt.receipt_digest
                    for receipt in receipts
                ),
                "state_digest": state_digest,
            },),
        )

    if kind == "moviechat.long.append":
        frames_ref = _tensor_ref(
            payload.get("frames_ref"),
            "MovieChat direct long frames_ref",
        )
        frames = _materialize_frames(
            binding.tensor_store,
            frames_ref,
            schema_id=_FRAGMENT_SCHEMA,
            field_name="MovieChat direct long frames",
        )
        if not frames:
            raise ValueError(
                "MovieChat direct append requires frames"
            )
        long.extend(frames)
        compressed, receipts = consolidate_direct_long_memory(
            tuple(long),
            target_length=long_limit,
        )
        long = list(compressed)
        long_ref = _store_frames(
            binding.tensor_store,
            tuple(long),
            schema_id=_LONG_SCHEMA,
        )
        state_digest = _state_digest(
            short_ref=short_ref,
            temp_short_ref=temp_short_ref,
            long_ref=long_ref,
        )
        result = {
            "input_frames_tensor_digest": (
                frames_ref.tensor_digest
            ),
            "long_memory_length": len(long),
            "long_memory_ref": _ref_payload(long_ref),
            "long_merge_receipts": tuple(
                receipt.payload() for receipt in receipts
            ),
            "source_paper_divergence": (
                MOVIECHAT_REFERENCE_FIDELITY
                .executable_long_memory_divergence
            ),
            "state_digest": state_digest,
        }
        return ProgramNodeResult(
            value=result,
            state_update={
                "long_memory_ref": _ref_payload(long_ref),
                "result": result,
            },
            events=({
                "type": "moviechat_direct_long_memory_updated",
                "input_frames_tensor_digest": (
                    frames_ref.tensor_digest
                ),
                "long_tensor_digest": _ref_digest(long_ref),
                "merge_receipt_digests": tuple(
                    receipt.receipt_digest
                    for receipt in receipts
                ),
                "state_digest": state_digest,
            },),
        )

    if kind == "moviechat.memory.read":
        mode = _text(
            payload.get("mode"),
            "MovieChat read mode",
        )
        if mode not in {"global", "breakpoint"}:
            raise ValueError(
                "MovieChat read mode must be global or breakpoint"
            )
        evicted_temp = 0
        evicted_long = 0
        source_current_omitted = False

        if mode == "global":
            frames = tuple(long)
        else:
            current_ref = _tensor_ref(
                payload.get("current_frame_ref"),
                "MovieChat current_frame_ref",
            )
            current = _materialize_frame(
                binding.tensor_store,
                current_ref,
                schema_id=_FRAME_SCHEMA,
                field_name="MovieChat breakpoint current frame",
            )
            while (
                len(long) + len(temp_short) + 1
                > position_capacity
            ):
                if temp_short:
                    temp_short.pop(0)
                    evicted_temp += 1
                elif long:
                    long.pop(0)
                    evicted_long += 1
                else:
                    break
            if not long:
                frames = tuple(temp_short)
                source_current_omitted = True
            else:
                frames = (
                    *tuple(long),
                    *tuple(temp_short),
                    current,
                )

            temp_short_ref = _store_frames(
                binding.tensor_store,
                tuple(temp_short),
                schema_id=_TEMP_SHORT_SCHEMA,
            )
            long_ref = _store_frames(
                binding.tensor_store,
                tuple(long),
                schema_id=_LONG_SCHEMA,
            )

        readout_ref = _store_frames(
            binding.tensor_store,
            tuple(frames),
            schema_id=_READOUT_SCHEMA,
        )
        state_digest = _state_digest(
            short_ref=short_ref,
            temp_short_ref=temp_short_ref,
            long_ref=long_ref,
        )
        result = {
            "mode": mode,
            "readout_ref": _ref_payload(readout_ref),
            "readout_tensor_digest": _ref_digest(readout_ref),
            "frame_count": len(frames),
            "position_indices": tuple(range(len(frames))),
            "position_capacity": position_capacity,
            "evicted_temp_short_count": evicted_temp,
            "evicted_long_count": evicted_long,
            "source_current_frame_omitted": (
                source_current_omitted
            ),
            "readout_role": "video_qformer_history",
            "state_digest": state_digest,
        }
        return ProgramNodeResult(
            value=result,
            state_update={
                "temp_short_memory_ref": _ref_payload(
                    temp_short_ref
                ),
                "long_memory_ref": _ref_payload(long_ref),
                "result": result,
            },
            events=({
                "type": "moviechat_memory_read",
                "mode": mode,
                "frame_count": len(frames),
                "readout_tensor_digest": _ref_digest(
                    readout_ref
                ),
                "evicted_temp_short_count": evicted_temp,
                "evicted_long_count": evicted_long,
                "source_current_frame_omitted": (
                    source_current_omitted
                ),
                "state_digest": state_digest,
            },),
        )

    if kind == "moviechat.memory.reset":
        state_digest = _state_digest(
            short_ref=None,
            temp_short_ref=None,
            long_ref=None,
        )
        result = {
            "state_digest": state_digest,
            "cleared": True,
        }
        return ProgramNodeResult(
            value=result,
            state_update={
                "short_memory_ref": None,
                "temp_short_memory_ref": None,
                "long_memory_ref": None,
                "sequence": 0,
                "result": result,
            },
            events=({
                "type": "moviechat_memory_reset",
                "state_digest": state_digest,
            },),
        )

    raise ValueError(
        f"unsupported MovieChat memory event: {kind}"
    )


def build_moviechat_memory_program() -> ResearchProgram:
    return (
        MemoryProgramBuilder.create(
            program_id="moviechat.sparse-video-memory",
            version=MOVIECHAT_AUDITED_COMMIT[:12],
            state_schema="moviechat.sparse-video-memory.state.v2",
            entrypoint="dispatch",
        )
        .custom(
            "dispatch",
            "moviechat.memory.dispatch",
            configuration={
                "memory_concerns": (
                    MemoryConcern.WRITE.value,
                    MemoryConcern.RETRIEVAL.value,
                    MemoryConcern.CONSOLIDATION.value,
                    MemoryConcern.RETENTION.value,
                ),
                "source_commit": MOVIECHAT_AUDITED_COMMIT,
                "short_memory_length": (
                    MOVIECHAT_REFERENCE_FIDELITY
                    .short_memory_length
                ),
                "short_memory_merge": (
                    MOVIECHAT_REFERENCE_FIDELITY
                    .short_memory_merge
                ),
                "long_memory_length": (
                    MOVIECHAT_REFERENCE_FIDELITY
                    .long_memory_length
                ),
                "position_capacity": (
                    MOVIECHAT_REFERENCE_FIDELITY
                    .position_capacity
                ),
                "tensor_state": (
                    "content-addressed-reference-only"
                ),
            },
            next_node="dispatch",
        )
        .build()
    )


MOVIECHAT_MEMORY_PROGRAM = build_moviechat_memory_program()


def moviechat_memory_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "moviechat.memory.dispatch",
            _dispatch,
            canonical_digest({
                "operation": "moviechat.memory.dispatch",
                "source_commit": MOVIECHAT_AUDITED_COMMIT,
                "implementation_revision": 2,
            }),
        ),
    )


def moviechat_memory_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="moviechat.sparse-video-memory",
        program=MOVIECHAT_MEMORY_PROGRAM,
        operations=moviechat_memory_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=4,
        dependency_identity={
            "source_commit": MOVIECHAT_AUDITED_COMMIT,
            "memory_fidelity": canonical_digest({
                "short_similarity": (
                    MOVIECHAT_REFERENCE_FIDELITY
                    .short_similarity
                ),
                "short_merge": (
                    MOVIECHAT_REFERENCE_FIDELITY.short_merge
                ),
                "direct_long_similarity": (
                    MOVIECHAT_REFERENCE_FIDELITY
                    .direct_long_similarity
                ),
                "direct_long_pair_selection": (
                    MOVIECHAT_REFERENCE_FIDELITY
                    .direct_long_pair_selection
                ),
                "breakpoint_eviction_order": (
                    MOVIECHAT_REFERENCE_FIDELITY
                    .breakpoint_eviction_order
                ),
                "tensor_state": (
                    "content-addressed-reference-only"
                ),
            }),
        },
    )


__all__ = [
    "MOVIECHAT_MEMORY_PROGRAM",
    "MovieChatMemoryBinding",
    "MovieChatMergeReceipt",
    "build_moviechat_memory_program",
    "consolidate_direct_long_memory",
    "consolidate_short_memory",
    "moviechat_memory_host",
    "moviechat_memory_initial_data",
    "moviechat_memory_operations",
]
