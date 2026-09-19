from __future__ import annotations

from dataclasses import dataclass
import json

from noetrium_platform.evidence.observability.api import EventEnvelope


_OPERATION_STARTED = "OPERATION_STARTED"
_OPERATION_PREFIX = "OPERATION_"


CONSUMED_EVENT_TYPES = (
    "OPERATION_STARTED",
    "OPERATION_SUCCEEDED",
    "OPERATION_FAILED",
    "OPERATION_CANCELLED",
    "OPERATION_INTERRUPTED",
)


@dataclass(frozen=True, slots=True)
class OperationInvocationProjection:
    values: tuple[object, ...]


def _projection_values(
    *,
    event_id: str,
    event_type: str,
    timestamp: float,
    component_id: str,
    context: object,
    payload: dict[str, object],
    encoded_payload: str,
) -> tuple[object, ...] | None:
    if not event_type.startswith(_OPERATION_PREFIX):
        return None
    invocation_id = payload.get("operation_invocation_id")
    operation_id = payload.get("operation_id")
    operation_type = payload.get("operation_type")
    if not all(isinstance(value, str) and value for value in (invocation_id, operation_id, operation_type)):
        return None

    started = event_type == _OPERATION_STARTED
    terminal = not started
    status = payload.get("status") if terminal else None
    failure_id = payload.get("failure_id") if terminal else None
    return (
        invocation_id,
        operation_id,
        operation_type,
        getattr(context, "run_id", None) if not isinstance(context, dict) else context.get("run_id"),
        getattr(context, "task_id", None) if not isinstance(context, dict) else context.get("task_id"),
        getattr(context, "decision_cycle_id", None) if not isinstance(context, dict) else context.get("decision_cycle_id"),
        getattr(context, "trace_id", None) if not isinstance(context, dict) else context.get("trace_id"),
        getattr(context, "span_id", None) if not isinstance(context, dict) else context.get("span_id"),
        payload.get("caller_component_id"),
        payload.get("target_component_id") or component_id,
        event_id if started else None,
        timestamp if started else None,
        event_id if terminal else None,
        event_type if terminal else None,
        timestamp if terminal else None,
        status,
        failure_id,
        encoded_payload,
    )


def event_operation_projection(event: EventEnvelope) -> OperationInvocationProjection | None:
    values = _projection_values(
        event_id=event.event_id,
        event_type=event.event_type,
        timestamp=event.timestamp,
        component_id=event.component_id,
        context=event.context,
        payload=event.payload,
        encoded_payload=json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True),
    )
    return None if values is None else OperationInvocationProjection(values)


def raw_event_operation_projection(payload: dict[str, object]) -> OperationInvocationProjection | None:
    event_payload = payload.get("payload")
    context = payload.get("context")
    if not isinstance(event_payload, dict) or not isinstance(context, dict):
        return None
    event_id = payload.get("event_id")
    event_type = payload.get("event_type")
    component_id = payload.get("component_id")
    timestamp = payload.get("timestamp")
    if not isinstance(event_id, str) or not isinstance(event_type, str):
        return None
    if not isinstance(component_id, str):
        component_id = "unknown"
    try:
        timestamp_value = float(timestamp)
    except (TypeError, ValueError):
        return None
    values = _projection_values(
        event_id=event_id,
        event_type=event_type,
        timestamp=timestamp_value,
        component_id=component_id,
        context=context,
        payload=event_payload,
        encoded_payload=json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )
    return None if values is None else OperationInvocationProjection(values)


__all__ = [
    "OperationInvocationProjection",
    "event_operation_projection",
    "raw_event_operation_projection",
]
