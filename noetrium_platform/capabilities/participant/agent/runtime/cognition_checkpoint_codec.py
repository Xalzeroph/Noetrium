from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, freeze_json

from ..api.cognition import AgentActionSummary, AgentLoopCheckpoint, AgentReceiptCheckpoint
from ..api.memory_checkpoint import AgentMemoryCheckpoint


_FIELDS = frozenset({
    "schema_version",
    "session_id",
    "goal_digest",
    "step",
    "plan_calls",
    "no_progress_steps",
    "same_action_runs",
    "last_observation_digest",
    "action_summaries",
    "last_receipt",
    "memory_checkpoint",
})
_SUMMARY_FIELDS = frozenset({
    "action_id",
    "action_type",
    "skill_id",
    "accepted",
    "verified",
    "observation_digest",
    "rationale",
    "payload",
    "timeout_s",
})
_RECEIPT_FIELDS = frozenset({
    "action_id",
    "action_type",
    "skill_id",
    "sequence_id",
    "accepted",
    "verified",
    "effect_id",
    "effect_certainty",
    "diagnostics",
    "payload",
})


def _exact(value: JsonValue, expected: frozenset[str], label: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    if frozenset(value) != expected:
        raise ValueError(f"{label} fields mismatch")
    return value


def _text(value: JsonValue, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{label} must be text")
    return value


def _integer(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _optional_bool(value: JsonValue, label: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{label} must be boolean or null")
    return value


def _object(value: JsonValue, label: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _summary_payload(summary: AgentActionSummary) -> JsonObject:
    return {
        "action_id": summary.action_id,
        "action_type": summary.action_type,
        "skill_id": summary.skill_id,
        "accepted": summary.accepted,
        "verified": summary.verified,
        "observation_digest": summary.observation_digest,
        "rationale": summary.rationale,
        "payload": dict(summary.payload),
        "timeout_s": float(summary.timeout_s),
    }


def _receipt_payload(receipt: AgentReceiptCheckpoint) -> JsonObject:
    return {
        "action_id": receipt.action_id,
        "action_type": receipt.action_type,
        "skill_id": receipt.skill_id,
        "sequence_id": receipt.sequence_id,
        "accepted": receipt.accepted,
        "verified": receipt.verified,
        "effect_id": receipt.effect_id,
        "effect_certainty": receipt.effect_certainty,
        "diagnostics": dict(receipt.diagnostics),
        "payload": dict(receipt.payload),
    }


def agent_loop_checkpoint_to_payload(checkpoint: AgentLoopCheckpoint) -> JsonObject:
    """Encode an Agent Turn VM checkpoint as canonical JSON-compatible data."""

    if not isinstance(checkpoint, AgentLoopCheckpoint):
        raise TypeError("checkpoint must be AgentLoopCheckpoint")
    payload: JsonObject = {
        "schema_version": checkpoint.schema_version,
        "session_id": checkpoint.session_id,
        "goal_digest": checkpoint.goal_digest,
        "step": checkpoint.step,
        "plan_calls": checkpoint.plan_calls,
        "no_progress_steps": checkpoint.no_progress_steps,
        "same_action_runs": checkpoint.same_action_runs,
        "last_observation_digest": checkpoint.last_observation_digest,
        "action_summaries": [_summary_payload(row) for row in checkpoint.action_summaries],
        "last_receipt": None if checkpoint.last_receipt is None else _receipt_payload(checkpoint.last_receipt),
        "memory_checkpoint": None if checkpoint.memory_checkpoint is None else checkpoint.memory_checkpoint.to_dict(),
    }
    return dict(freeze_json(payload))


def _decode_summary(value: JsonValue) -> AgentActionSummary:
    row = _exact(value, _SUMMARY_FIELDS, "agent action summary")
    accepted = row["accepted"]
    if not isinstance(accepted, bool):
        raise ValueError("agent action summary accepted must be boolean")
    timeout_s = row["timeout_s"]
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
        raise ValueError("agent action summary timeout_s must be numeric")
    return AgentActionSummary(
        action_id=_text(row["action_id"], "action_id"),
        action_type=_text(row["action_type"], "action_type"),
        skill_id=_text(row["skill_id"], "skill_id"),
        accepted=accepted,
        verified=_optional_bool(row["verified"], "verified"),
        observation_digest=_text(row["observation_digest"], "observation_digest", allow_empty=True),
        rationale=_text(row["rationale"], "rationale", allow_empty=True),
        payload=_object(row["payload"], "summary payload"),
        timeout_s=float(timeout_s),
    )


def _decode_receipt(value: JsonValue) -> AgentReceiptCheckpoint:
    row = _exact(value, _RECEIPT_FIELDS, "agent receipt checkpoint")
    accepted = row["accepted"]
    if not isinstance(accepted, bool):
        raise ValueError("agent receipt accepted must be boolean")
    effect_id = row["effect_id"]
    if effect_id is not None:
        effect_id = _text(effect_id, "effect_id")
    return AgentReceiptCheckpoint(
        action_id=_text(row["action_id"], "action_id"),
        action_type=_text(row["action_type"], "action_type"),
        skill_id=_text(row["skill_id"], "skill_id"),
        sequence_id=_text(row["sequence_id"], "sequence_id"),
        accepted=accepted,
        verified=_optional_bool(row["verified"], "verified"),
        effect_id=effect_id,
        effect_certainty=_text(row["effect_certainty"], "effect_certainty"),
        diagnostics=_object(row["diagnostics"], "receipt diagnostics"),
        payload=_object(row["payload"], "receipt payload"),
    )


def agent_loop_checkpoint_from_payload(value: JsonValue) -> AgentLoopCheckpoint:
    """Decode fail-closed; unknown or missing fields are never ignored."""

    row = _exact(value, _FIELDS, "agent loop checkpoint")
    summaries_value = row["action_summaries"]
    if isinstance(summaries_value, (str, bytes, bytearray)) or not isinstance(summaries_value, Sequence):
        raise ValueError("action_summaries must be a sequence")
    summaries = tuple(_decode_summary(item) for item in summaries_value)

    receipt_value = row["last_receipt"]
    receipt = None if receipt_value is None else _decode_receipt(receipt_value)

    memory_value = row["memory_checkpoint"]
    memory = None
    if memory_value is not None:
        memory_row = _object(memory_value, "memory_checkpoint")
        memory = AgentMemoryCheckpoint.from_dict(memory_row)

    return AgentLoopCheckpoint(
        schema_version=_text(row["schema_version"], "schema_version"),
        session_id=_text(row["session_id"], "session_id"),
        goal_digest=_text(row["goal_digest"], "goal_digest"),
        step=_integer(row["step"], "step"),
        plan_calls=_integer(row["plan_calls"], "plan_calls"),
        no_progress_steps=_integer(row["no_progress_steps"], "no_progress_steps"),
        same_action_runs=_integer(row["same_action_runs"], "same_action_runs"),
        last_observation_digest=_text(row["last_observation_digest"], "last_observation_digest", allow_empty=True),
        action_summaries=summaries,
        last_receipt=receipt,
        memory_checkpoint=memory,
    )


__all__ = [
    "agent_loop_checkpoint_from_payload",
    "agent_loop_checkpoint_to_payload",
]
