from __future__ import annotations

import json

from noetrium_platform.infrastructure.reliability.diagnostics.api import (
    DiagnosticObjectRecord,
    StateWriterRecord,
)

OBJECT_COLUMNS = (
    "object_id",
    "kind",
    "run_id",
    "task_id",
    "decision_cycle_id",
    "trace_id",
    "span_id",
    "component_id",
    "timestamp",
    "payload_json",
)
OBJECT_SELECT = ",".join(OBJECT_COLUMNS)

STATE_COLUMNS = (
    "mutation_id",
    "state_name",
    "run_id",
    "task_id",
    "decision_cycle_id",
    "trace_id",
    "span_id",
    "component_id",
    "operation_id",
    "new_version",
    "new_digest",
    "timestamp",
    "payload_json",
)
STATE_SELECT = ",".join(STATE_COLUMNS)


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    return value


def _optional_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field=field)


def _required_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _required_float(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    return float(value)


def _optional_float(value: object, *, field: str) -> float | None:
    if value is None:
        return None
    return _required_float(value, field=field)


def _decode_payload(raw: object, *, record_kind: str) -> dict[str, object]:
    if not isinstance(raw, str):
        raise ValueError(f"{record_kind} payload must be stored as text")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{record_kind} payload must contain valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{record_kind} payload must decode to an object")
    return payload


def decode_object_record(row: tuple[object, ...]) -> DiagnosticObjectRecord:
    if len(row) != len(OBJECT_COLUMNS):
        raise ValueError("diagnostic object projection row has invalid width")
    (
        object_id,
        kind,
        run_id,
        task_id,
        decision_cycle_id,
        trace_id,
        span_id,
        component_id,
        timestamp,
        payload_json,
    ) = row
    return DiagnosticObjectRecord(
        object_id=_required_text(object_id, field="object_id"),
        kind=_required_text(kind, field="kind"),
        run_id=_optional_text(run_id, field="run_id"),
        task_id=_optional_text(task_id, field="task_id"),
        decision_cycle_id=_optional_text(decision_cycle_id, field="decision_cycle_id"),
        trace_id=_optional_text(trace_id, field="trace_id"),
        span_id=_optional_text(span_id, field="span_id"),
        component_id=_optional_text(component_id, field="component_id"),
        timestamp=_optional_float(timestamp, field="timestamp"),
        payload=_decode_payload(payload_json, record_kind="diagnostic object"),
    )


def decode_state_writer_record(row: tuple[object, ...]) -> StateWriterRecord:
    if len(row) != len(STATE_COLUMNS):
        raise ValueError("state-writer projection row has invalid width")
    (
        mutation_id,
        state_name,
        run_id,
        task_id,
        decision_cycle_id,
        trace_id,
        span_id,
        component_id,
        operation_id,
        new_version,
        new_digest,
        timestamp,
        payload_json,
    ) = row
    return StateWriterRecord(
        mutation_id=_required_text(mutation_id, field="mutation_id"),
        state_name=_required_text(state_name, field="state_name"),
        run_id=_required_text(run_id, field="run_id"),
        task_id=_optional_text(task_id, field="task_id"),
        decision_cycle_id=_optional_text(decision_cycle_id, field="decision_cycle_id"),
        trace_id=_optional_text(trace_id, field="trace_id"),
        span_id=_optional_text(span_id, field="span_id"),
        component_id=_required_text(component_id, field="component_id"),
        operation_id=_required_text(operation_id, field="operation_id"),
        new_version=_required_int(new_version, field="new_version"),
        new_digest=_required_text(new_digest, field="new_digest"),
        timestamp=_required_float(timestamp, field="timestamp"),
        payload=_decode_payload(payload_json, record_kind="state writer"),
    )


__all__ = [
    "OBJECT_COLUMNS",
    "OBJECT_SELECT",
    "STATE_COLUMNS",
    "STATE_SELECT",
    "decode_object_record",
    "decode_state_writer_record",
]
