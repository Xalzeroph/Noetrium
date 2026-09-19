from __future__ import annotations

from collections.abc import Mapping, Sequence
import math

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

from .fidelity import VCA_REFERENCE_FIDELITY


_VIDEO_SAMPLE_CAPABILITY = "artifact.video.decode"
_REWARD_AGENT_ID = "vca.shared-vlm.reward"
_EXPLORATION_AGENT_ID = "vca.shared-vlm.exploration"
VCA_EXECUTION_SAFETY_ROUNDS = 64


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"VCA {field} must be text")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"VCA {field} must be an integer >= {minimum}")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"VCA {field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"VCA {field} must be finite")
    return result


def _rows(value: object, field: str) -> tuple[Mapping[str, JsonValue], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"VCA {field} must be a sequence")
    rows = tuple(value)
    if any(not isinstance(row, Mapping) for row in rows):
        raise TypeError(f"VCA {field} must contain objects")
    return rows


def _segment(value: object, field: str = "segment") -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"VCA {field} must be an object")
    _text(value.get("segment_id"), f"{field} id")
    start = _integer(value.get("start_frame"), f"{field} start_frame")
    end = _integer(value.get("end_frame"), f"{field} end_frame")
    if end <= start:
        raise ValueError(f"VCA {field} must have positive span")
    _integer(value.get("depth"), f"{field} depth")
    return value


def vca_initial_state(
    *,
    task_id: str,
    video_ref: str,
    question: str,
    start_frame: int,
    end_frame: int,
    sampling_frame_number: int,
    memory_limit: int,
    max_rounds: int = 32,
) -> JsonObject:
    start = _integer(start_frame, "start_frame")
    end = _integer(end_frame, "end_frame")
    if end <= start:
        raise ValueError("VCA video interval must have positive span")
    samples = _integer(sampling_frame_number, "sampling_frame_number", minimum=1)
    memory = _integer(memory_limit, "memory_limit", minimum=1)
    rounds = _integer(max_rounds, "max_rounds", minimum=1)
    if rounds > VCA_EXECUTION_SAFETY_ROUNDS:
        raise ValueError("VCA max_rounds exceeds reproduction safety ceiling")
    root = {
        "segment_id": "root",
        "parent_id": "",
        "start_frame": start,
        "end_frame": end,
        "depth": 0,
        "reward": None,
        "explanation": "",
    }
    return {
        "task_id": _text(task_id, "task_id"),
        "video_ref": _text(video_ref, "video_ref"),
        "question": _text(question, "question"),
        "sampling_frame_number": samples,
        "memory_limit": memory,
        "max_rounds": rounds,
        "round_index": 0,
        "selected_segment": root,
        "candidate_segments": (),
        "reward_history": (),
        "memory_frames": (),
        "current_frames": (),
        "current_segments": (),
        "observed_frame_count": 0,
        "answer": "",
    }


def _prepare_sample(request: MethodNodeRequest) -> MethodNodeResult:
    selected = _segment(request.state.get("selected_segment"), "selected segment")
    return MethodNodeResult(
        value={
            "operation": "uniform_sample_segment",
            "video_ref": _text(request.state.get("video_ref"), "video_ref"),
            "segment": dict(selected),
            "sample_count": _integer(
                request.state.get("sampling_frame_number"),
                "sampling_frame_number",
                minimum=1,
            ),
        }
    )


def _record_sample(request: MethodNodeRequest) -> MethodNodeResult:
    if not isinstance(request.previous_value, Mapping):
        raise TypeError("VCA video decode result must be an object")
    frames = _rows(request.previous_value.get("frames"), "sampled frames")
    sample_count = _integer(
        request.state.get("sampling_frame_number"),
        "sampling_frame_number",
        minimum=1,
    )
    if len(frames) != sample_count:
        raise ValueError("VCA uniform sampler returned wrong frame count")
    selected = _segment(request.state.get("selected_segment"), "selected segment")
    start = _integer(selected.get("start_frame"), "selected start")
    end = _integer(selected.get("end_frame"), "selected end")
    indices: list[int] = []
    normalized_frames: list[JsonObject] = []
    for frame in frames:
        index = _integer(frame.get("frame_index"), "sample frame_index")
        if not start < index < end:
            raise ValueError("VCA sampled frame must lie inside selected segment")
        ref = _text(frame.get("frame_ref"), "sample frame_ref")
        indices.append(index)
        normalized_frames.append({"frame_index": index, "frame_ref": ref})
    if indices != sorted(indices) or len(indices) != len(set(indices)):
        raise ValueError("VCA sampled frames must be unique and ordered")

    boundaries = (start, *indices, end)
    round_number = _integer(request.state.get("round_index"), "round_index") + 1
    parent_id = _text(selected.get("segment_id"), "selected segment id")
    depth = _integer(selected.get("depth"), "selected depth") + 1
    segments = tuple(
        {
            "segment_id": f"{parent_id}/r{round_number}/s{index}",
            "parent_id": parent_id,
            "start_frame": boundaries[index],
            "end_frame": boundaries[index + 1],
            "depth": depth,
            "reward": None,
            "explanation": "",
        }
        for index in range(len(boundaries) - 1)
    )
    return MethodNodeResult(
        value={"frames": tuple(normalized_frames), "segments": segments},
        state_update={
            "current_frames": tuple(normalized_frames),
            "current_segments": segments,
            "observed_frame_count": (
                _integer(request.state.get("observed_frame_count"), "observed_frame_count")
                + len(normalized_frames)
            ),
        },
    )


def _reward_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "phase": "intrinsic_reward",
        "question": _text(request.state.get("question"), "question"),
        "segments": tuple(dict(row) for row in _rows(
            request.state.get("current_segments"), "current segments"
        )),
        "frames": tuple(dict(row) for row in _rows(
            request.state.get("current_frames"), "current frames"
        )),
        "reward_history": tuple(dict(row) for row in _rows(
            request.state.get("reward_history"), "reward history"
        )),
        "temperature": VCA_REFERENCE_FIDELITY.temperature,
        "instruction": (
            "Explain each new sub-segment, then assign a relevance score "
            "from 0 to 100 while remaining consistent with reward history."
        ),
    }


def _record_reward(request: MethodNodeRequest) -> MethodNodeResult:
    if not isinstance(request.previous_value, Mapping):
        raise TypeError("VCA reward model result must be an object")
    scored = _rows(request.previous_value.get("segments"), "reward segments")
    expected = _rows(request.state.get("current_segments"), "current segments")
    expected_ids = tuple(_text(row.get("segment_id"), "segment id") for row in expected)
    if len(scored) != len(expected_ids):
        raise ValueError("VCA reward model must score every new segment")

    scored_by_id: dict[str, JsonObject] = {}
    history_rows: list[JsonObject] = []
    for row in scored:
        segment_id = _text(row.get("segment_id"), "reward segment_id")
        if segment_id not in expected_ids or segment_id in scored_by_id:
            raise ValueError("VCA reward model returned unknown or duplicate segment")
        score = _number(row.get("score"), "reward score")
        if not 0.0 <= score <= 100.0:
            raise ValueError("VCA reward score must be in [0, 100]")
        explanation = _text(row.get("explanation"), "reward explanation")
        base = dict(expected[expected_ids.index(segment_id)])
        base.update({"reward": score, "explanation": explanation})
        scored_by_id[segment_id] = base
        history_rows.append(
            {
                "round": _integer(request.state.get("round_index"), "round_index") + 1,
                "segment_id": segment_id,
                "score": score,
                "explanation": explanation,
            }
        )

    selected_id = _text(
        _segment(request.state.get("selected_segment"), "selected segment").get("segment_id"),
        "selected segment id",
    )
    prior = tuple(
        dict(row)
        for row in _rows(request.state.get("candidate_segments"), "candidate segments")
        if row.get("segment_id") != selected_id
    )
    children = tuple(scored_by_id[segment_id] for segment_id in expected_ids)
    history = (
        *tuple(dict(row) for row in _rows(request.state.get("reward_history"), "reward history")),
        *history_rows,
    )
    return MethodNodeResult(
        value={"scored_segments": children},
        state_update={
            "candidate_segments": (*prior, *children),
            "reward_history": history,
        },
    )


def _update_memory(request: MethodNodeRequest) -> MethodNodeResult:
    frames = _rows(request.state.get("current_frames"), "current frames")
    segments = _rows(request.state.get("current_segments"), "current segments")
    candidates = {
        _text(row.get("segment_id"), "candidate id"): row
        for row in _rows(request.state.get("candidate_segments"), "candidate segments")
    }
    segment_scores = [
        _number(candidates[_text(row.get("segment_id"), "segment id")].get("reward"), "reward")
        for row in segments
    ]
    new_memory: list[JsonObject] = []
    for index, frame in enumerate(frames):
        adjacent = segment_scores[index:index + 2]
        new_memory.append(
            {
                "frame_index": _integer(frame.get("frame_index"), "frame_index"),
                "frame_ref": _text(frame.get("frame_ref"), "frame_ref"),
                "relevance": max(adjacent),
            }
        )
    existing = [
        dict(row) for row in _rows(request.state.get("memory_frames"), "memory frames")
    ]
    combined = existing + new_memory
    best_by_ref: dict[str, JsonObject] = {}
    for row in combined:
        ref = _text(row.get("frame_ref"), "memory frame_ref")
        current = best_by_ref.get(ref)
        if current is None or _number(row.get("relevance"), "frame relevance") > _number(
            current.get("relevance"), "frame relevance"
        ):
            best_by_ref[ref] = row
    limit = _integer(request.state.get("memory_limit"), "memory_limit", minimum=1)
    retained = sorted(
        best_by_ref.values(),
        key=lambda row: (
            -_number(row.get("relevance"), "frame relevance"),
            _integer(row.get("frame_index"), "frame_index"),
        ),
    )[:limit]
    retained.sort(key=lambda row: _integer(row.get("frame_index"), "frame_index"))
    return MethodNodeResult(
        value={"memory_size": len(retained)},
        state_update={"memory_frames": tuple(retained)},
    )


def _exploration_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "phase": "exploration",
        "question": _text(request.state.get("question"), "question"),
        "candidate_segments": tuple(
            dict(row)
            for row in _rows(request.state.get("candidate_segments"), "candidate segments")
        ),
        "memory_frames": tuple(
            dict(row) for row in _rows(request.state.get("memory_frames"), "memory frames")
        ),
        "reward_history": tuple(
            dict(row) for row in _rows(request.state.get("reward_history"), "reward history")
        ),
        "temperature": VCA_REFERENCE_FIDELITY.temperature,
        "instruction": (
            "Answer if evidence is sufficient; otherwise independently choose "
            "one candidate segment to explore. Reward scores are guidance, not "
            "a greedy selection rule, and earlier coarse candidates may be revisited."
        ),
    }


def _record_decision(request: MethodNodeRequest) -> MethodNodeResult:
    if not isinstance(request.previous_value, Mapping):
        raise TypeError("VCA exploration result must be an object")
    answer = request.previous_value.get("answer")
    segment_id = request.previous_value.get("segment_id")
    round_index = _integer(request.state.get("round_index"), "round_index") + 1
    if isinstance(answer, str) and answer.strip():
        return MethodNodeResult(
            value={"answer": answer.strip(), "round": round_index},
            state_update={"answer": answer.strip(), "round_index": round_index},
            next_node="return",
        )
    if not isinstance(segment_id, str) or not segment_id.strip():
        raise ValueError("VCA exploration must answer or select a segment")
    candidates = _rows(request.state.get("candidate_segments"), "candidate segments")
    selected = next(
        (dict(row) for row in candidates if row.get("segment_id") == segment_id),
        None,
    )
    if selected is None:
        raise ValueError("VCA exploration selected unknown candidate segment")
    max_rounds = _integer(request.state.get("max_rounds"), "max_rounds", minimum=1)
    if round_index >= max_rounds:
        raise RuntimeError("VCA reproduction safety round ceiling reached before answer")
    return MethodNodeResult(
        value={"segment_id": segment_id, "round": round_index},
        state_update={
            "selected_segment": selected,
            "round_index": round_index,
            "current_frames": (),
            "current_segments": (),
        },
        next_node="prepare_sample",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    answer = _text(request.state.get("answer"), "answer")
    return MethodNodeResult(
        value={
            "answer": answer,
            "exploration_rounds": _integer(request.state.get("round_index"), "round_index"),
            "observed_frame_count": _integer(
                request.state.get("observed_frame_count"), "observed_frame_count"
            ),
            "memory_frames": tuple(
                dict(row) for row in _rows(request.state.get("memory_frames"), "memory frames")
            ),
            "candidate_segments": tuple(
                dict(row)
                for row in _rows(request.state.get("candidate_segments"), "candidate segments")
            ),
            "reward_history": tuple(
                dict(row) for row in _rows(request.state.get("reward_history"), "reward history")
            ),
        }
    )


def build_vca_method_program() -> MethodProgram:
    configuration: JsonObject = {
        "paper": "ICCV 2025",
        "algorithm": (
            "uniform_sample_selected_segment",
            "self_generated_intrinsic_reward",
            "fixed_relevance_memory",
            "non_greedy_tree_exploration_or_answer",
        ),
        "shared_vlm_for_reward_and_exploration": True,
        "reward_history_conditioning": True,
        "temperature": VCA_REFERENCE_FIDELITY.temperature,
        "sampling_frame_number": "study-bound",
        "memory_limit": "benchmark-bound",
        "max_rounds": "reproduction-safety-bound",
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="vca-video-curious-agent",
            implementation_version="iccv-2025-paper-authoritative",
            abi_version="noetrium.method-machine.v1",
            schema_version="vca.iccv2025.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    visits = VCA_EXECUTION_SAFETY_ROUNDS
    builder = MethodProgramBuilder(identity, entrypoint="prepare_sample")
    builder.compute(
        "prepare_sample",
        "vca.video.uniform-sample.prepare",
        _prepare_sample,
        ("sample_video",),
        max_visits=visits,
    )
    builder.capability(
        "sample_video",
        "vca.video.uniform-sample",
        _VIDEO_SAMPLE_CAPABILITY,
        ("record_sample",),
        effect_class=EffectClass.PURE,
        evidence_obligations=("video.sample",),
        max_visits=visits,
    )
    builder.compute(
        "record_sample",
        "vca.video.uniform-sample.record",
        _record_sample,
        ("reward",),
        max_visits=visits,
    )
    builder.agent(
        "reward",
        "vca.intrinsic-reward",
        _REWARD_AGENT_ID,
        ("record_reward",),
        view_handler=_reward_view,
        max_visits=visits,
    )
    builder.compute(
        "record_reward",
        "vca.reward.record",
        _record_reward,
        ("update_memory",),
        max_visits=visits,
    )
    builder.compute(
        "update_memory",
        "vca.memory.relevance-prune",
        _update_memory,
        ("explore",),
        max_visits=visits,
    )
    builder.agent(
        "explore",
        "vca.tree-explore-or-answer",
        _EXPLORATION_AGENT_ID,
        ("record_decision",),
        view_handler=_exploration_view,
        max_visits=visits,
    )
    builder.route(
        "record_decision",
        "vca.decision.record",
        _record_decision,
        ("prepare_sample", "return"),
        max_visits=visits,
    )
    builder.return_node("return", "vca.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(_VIDEO_SAMPLE_CAPABILITY,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "video.sample",
            "vca.intrinsic-reward-history",
            "vca.memory-buffer",
            "vca.exploration-trajectory",
            "model.invocation",
        ),
        metric_names=(
            "multiple_choice_accuracy",
            "observed_frame_count",
            "exploration_rounds",
        ),
        artifact_kinds=("vca_exploration_trajectory", "vca_memory_buffer"),
    )


VCA_METHOD_PROGRAM = build_vca_method_program()


__all__ = [
    "VCA_EXECUTION_SAFETY_ROUNDS",
    "VCA_METHOD_PROGRAM",
    "build_vca_method_program",
    "vca_initial_state",
]
