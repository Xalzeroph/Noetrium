from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import math
import re
import time

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_bytes

from .runtime_history_contracts import (
    RUNTIME_HISTORY_ROW_SCHEMA_VERSION,
    RuntimeHistoryEntry,
    RuntimeHistoryProjectionKind,
)
from .runtime_state_contracts import RuntimeControlState, RuntimeTxnPhase

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STATE_FIELDS = frozenset({
    "control_id", "manifest_digest", "phase", "completed_actions", "current_action",
    "current_mutating", "evidence_refs", "last_error_type", "last_error",
    "last_error_digest", "updated_at",
})


def runtime_state_dict(state: RuntimeControlState) -> dict[str, JsonValue]:
    if not isinstance(state, RuntimeControlState):
        raise TypeError("runtime history requires RuntimeControlState")
    return {
        "control_id": state.control_id,
        "manifest_digest": state.manifest_digest,
        "phase": state.phase.value,
        "completed_actions": tuple(state.completed_actions),
        "current_action": state.current_action,
        "current_mutating": state.current_mutating,
        "evidence_refs": tuple(state.evidence_refs),
        "last_error_type": state.last_error_type,
        "last_error": state.last_error,
        "last_error_digest": state.last_error_digest,
        "updated_at": state.updated_at,
    }


def _optional_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"runtime history state {field} must be text or null")
    return value


def _string_sequence(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"runtime history state {field} must be a string sequence")
    return tuple(value)


def runtime_state_from_json(value: object) -> RuntimeControlState:
    if not isinstance(value, dict) or frozenset(value) != _STATE_FIELDS:
        raise ValueError("runtime history state field set is invalid")
    control_id = value["control_id"]
    manifest_digest = value["manifest_digest"]
    if not isinstance(control_id, str) or not control_id.strip():
        raise ValueError("runtime history state control_id required")
    if not isinstance(manifest_digest, str) or not manifest_digest.strip():
        raise ValueError("runtime history state manifest_digest required")
    current_mutating = value["current_mutating"]
    if not isinstance(current_mutating, bool):
        raise ValueError("runtime history state current_mutating must be bool")
    updated_at = value["updated_at"]
    if isinstance(updated_at, bool) or not isinstance(updated_at, (int, float)) or not math.isfinite(updated_at):
        raise ValueError("runtime history state updated_at must be finite numeric")
    try:
        phase = RuntimeTxnPhase(value["phase"])
    except (TypeError, ValueError) as exc:
        raise ValueError("runtime history state phase is invalid") from exc
    return RuntimeControlState(
        control_id=control_id,
        manifest_digest=manifest_digest,
        phase=phase,
        completed_actions=_string_sequence(value["completed_actions"], field="completed_actions"),
        current_action=_optional_text(value["current_action"], field="current_action"),
        current_mutating=current_mutating,
        evidence_refs=_string_sequence(value["evidence_refs"], field="evidence_refs"),
        last_error_type=_optional_text(value["last_error_type"], field="last_error_type"),
        last_error=_optional_text(value["last_error"], field="last_error"),
        last_error_digest=_optional_text(value["last_error_digest"], field="last_error_digest"),
        updated_at=float(updated_at),
    )


def runtime_state_digest(state: RuntimeControlState) -> str:
    return hashlib.sha256(canonical_bytes(runtime_state_dict(state))).hexdigest()


def build_runtime_history_row(
    *,
    sequence: int,
    state: RuntimeControlState,
    projection_kind: RuntimeHistoryProjectionKind,
    previous_sha256: str | None,
) -> tuple[dict[str, JsonValue], RuntimeHistoryEntry]:
    state_document = runtime_state_dict(state)
    state_sha256 = runtime_state_digest(state)
    timestamp = time.time()
    base: dict[str, JsonValue] = {
        "schema_version": RUNTIME_HISTORY_ROW_SCHEMA_VERSION,
        "sequence": sequence,
        "timestamp": timestamp,
        "state": state_document,
        "state_sha256": state_sha256,
        "projection_kind": projection_kind.value,
        "previous_sha256": previous_sha256,
    }
    row_sha256 = hashlib.sha256(canonical_bytes(base)).hexdigest()
    row = {**base, "row_sha256": row_sha256}
    entry = RuntimeHistoryEntry(
        sequence=sequence,
        timestamp=timestamp,
        state=state,
        state_sha256=state_sha256,
        projection_kind=projection_kind,
        previous_sha256=previous_sha256,
        row_sha256=row_sha256,
    )
    return row, entry


def encode_runtime_history_row(row: Mapping[str, JsonValue]) -> bytes:
    return json.dumps(
        row,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"


def runtime_history_entry_from_document(document: object) -> RuntimeHistoryEntry:
    expected_fields = {
        "schema_version", "sequence", "timestamp", "state", "state_sha256",
        "projection_kind", "previous_sha256", "row_sha256",
    }
    if not isinstance(document, dict) or set(document) != expected_fields:
        raise ValueError("runtime history row field set is invalid")
    if document["schema_version"] != RUNTIME_HISTORY_ROW_SCHEMA_VERSION:
        raise ValueError("runtime history row schema is unsupported")
    sequence = document["sequence"]
    timestamp = document["timestamp"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
        raise ValueError("runtime history sequence must be positive integer")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
        raise ValueError("runtime history timestamp must be finite numeric")
    state_sha256 = document["state_sha256"]
    row_sha256 = document["row_sha256"]
    previous_sha256 = document["previous_sha256"]
    if not isinstance(state_sha256, str) or not _SHA256.fullmatch(state_sha256):
        raise ValueError("runtime history state_sha256 is invalid")
    if not isinstance(row_sha256, str) or not _SHA256.fullmatch(row_sha256):
        raise ValueError("runtime history row_sha256 is invalid")
    if previous_sha256 is not None and (
        not isinstance(previous_sha256, str) or not _SHA256.fullmatch(previous_sha256)
    ):
        raise ValueError("runtime history previous_sha256 is invalid")
    try:
        projection_kind = RuntimeHistoryProjectionKind(document["projection_kind"])
    except (TypeError, ValueError) as exc:
        raise ValueError("runtime history projection kind is invalid") from exc
    state = runtime_state_from_json(document["state"])
    if runtime_state_digest(state) != state_sha256:
        raise ValueError("runtime history state digest mismatch")
    base = dict(document)
    base.pop("row_sha256")
    if hashlib.sha256(canonical_bytes(base)).hexdigest() != row_sha256:
        raise ValueError("runtime history row digest mismatch")
    return RuntimeHistoryEntry(
        sequence=sequence,
        timestamp=float(timestamp),
        state=state,
        state_sha256=state_sha256,
        projection_kind=projection_kind,
        previous_sha256=previous_sha256,
        row_sha256=row_sha256,
    )


__all__ = [
    "build_runtime_history_row",
    "encode_runtime_history_row",
    "runtime_history_entry_from_document",
    "runtime_state_dict",
    "runtime_state_digest",
    "runtime_state_from_json",
]
