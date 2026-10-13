from __future__ import annotations

import json
import re

from noetrium_platform.foundation.kernel.kernel import JsonDocument, canonical_bytes

from ..api.recovery import RecoveryStep
from ..api.recovery_state import DurableRecoveryAttempt, DurableRecoveryPhase

_SCHEMA = "model-serving-durable-recovery.v2"
_FIELDS = frozenset(
    {
        "attempt_id",
        "source_run_id",
        "plan_digest",
        "phase",
        "completed_steps",
        "current_step",
        "current_step_status",
        "current_effect_certainty",
        "evidence_refs",
        "updated_at",
    }
)
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_STATUS_VALUES = frozenset({"running", "completed", "failed"})
_CERTAINTY_VALUES = frozenset({"unknown", "no_effect", "confirmed"})


def encode_attempt_payload(attempt: DurableRecoveryAttempt) -> dict[str, object]:
    payload = json.loads(canonical_bytes(attempt).decode("utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("durable recovery payload must encode as an object")
    return payload


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"durable recovery {field} must be a string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"durable recovery {field} must be an array")
    result = tuple(_string(item, field) for item in value)
    if len(result) != len(set(result)) and field == "completed_steps":
        raise ValueError("durable recovery completed_steps contains duplicates")
    return result


def decode_attempt_payload(payload: JsonDocument) -> DurableRecoveryAttempt:
    if not isinstance(payload, dict):
        raise TypeError("durable recovery payload must be an object")
    if frozenset(payload) != _FIELDS:
        missing = sorted(_FIELDS - frozenset(payload))
        extra = sorted(frozenset(payload) - _FIELDS)
        raise ValueError(f"durable recovery fields mismatch: missing={missing}, extra={extra}")

    attempt_id = _string(payload["attempt_id"], "attempt_id")
    source_run_id = _string(payload["source_run_id"], "source_run_id")
    plan_digest = _string(payload["plan_digest"], "plan_digest")
    if not attempt_id or not source_run_id:
        raise ValueError("durable recovery identity fields must be non-empty")
    if _DIGEST_RE.fullmatch(plan_digest) is None:
        raise ValueError("durable recovery plan_digest must be a lowercase SHA-256 digest")

    phase_raw = _string(payload["phase"], "phase")
    phase = DurableRecoveryPhase(phase_raw)
    completed_steps = _string_tuple(payload["completed_steps"], "completed_steps")
    valid_steps = {step.value for step in RecoveryStep}
    if any(step not in valid_steps for step in completed_steps):
        raise ValueError("durable recovery completed_steps contains an unknown step")
    current_step = _optional_string(payload["current_step"], "current_step")
    current_status = _optional_string(payload["current_step_status"], "current_step_status")
    effect_certainty = _optional_string(
        payload["current_effect_certainty"], "current_effect_certainty"
    )
    if current_step is not None and current_step not in valid_steps:
        raise ValueError("durable recovery current_step is unknown")
    if current_status is not None and current_status not in _STATUS_VALUES:
        raise ValueError("durable recovery current_step_status is invalid")
    if effect_certainty is not None and effect_certainty not in _CERTAINTY_VALUES:
        raise ValueError("durable recovery current_effect_certainty is invalid")
    if current_step is None and (current_status is not None or effect_certainty is not None):
        raise ValueError("durable recovery current-step metadata requires current_step")
    if current_step is not None and (current_status is None or effect_certainty is None):
        raise ValueError("durable recovery current_step requires status and effect certainty")

    evidence_refs = _string_tuple(payload["evidence_refs"], "evidence_refs")
    updated_at = payload["updated_at"]
    if type(updated_at) is not float:
        raise TypeError("durable recovery updated_at must be a JSON float")

    if phase is DurableRecoveryPhase.PLANNED and (
        completed_steps or current_step is not None or evidence_refs
    ):
        raise ValueError("planned durable recovery state must be empty")
    if phase is DurableRecoveryPhase.SUCCEEDED and (
        current_step is not None or current_status is not None or effect_certainty is not None
    ):
        raise ValueError("succeeded durable recovery state cannot retain a current step")
    if current_status == "completed" and current_step not in completed_steps:
        raise ValueError("completed current_step must be present in completed_steps")

    return DurableRecoveryAttempt(
        attempt_id=attempt_id,
        source_run_id=source_run_id,
        plan_digest=plan_digest,
        phase=phase,
        completed_steps=completed_steps,
        current_step=current_step,
        current_step_status=current_status,
        current_effect_certainty=effect_certainty,
        evidence_refs=evidence_refs,
        updated_at=updated_at,
    )


__all__ = ["_SCHEMA", "decode_attempt_payload", "encode_attempt_payload"]
