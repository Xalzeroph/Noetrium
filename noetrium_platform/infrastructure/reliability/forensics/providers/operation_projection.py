from __future__ import annotations

from dataclasses import dataclass
import json

from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.record_plane import event_document


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
    if isinstance(context, dict):
        run_id = context.get("run_id")
        task_id = context.get("task_id")
        decision_cycle_id = context.get("decision_cycle_id")
        trace_id = context.get("trace_id")
        span_id = context.get("span_id")
    else:
        run_id = getattr(context, "run_id", None)
        task_id = getattr(context, "task_id", None)
        decision_cycle_id = getattr(context, "decision_cycle_id", None)
        trace_id = getattr(context, "trace_id", None)
        span_id = getattr(context, "span_id", None)
    return (
        invocation_id,
        operation_id,
        operation_type,
        run_id,
        task_id,
        decision_cycle_id,
        trace_id,
        span_id,
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


def event_document_operation_projection(
    doc: dict[str, object],
    *,
    encoded_payload: str | None = None,
) -> OperationInvocationProjection | None:
    event_payload = doc.get("payload")
    context = doc.get("context")
    event_type = doc.get("event_type")
    if (
        not isinstance(event_payload, dict)
        or not isinstance(context, dict)
        or not isinstance(event_type, str)
        or not event_type.startswith(_OPERATION_PREFIX)
    ):
        return None
    event_id = doc.get("event_id")
    component_id = doc.get("component_id")
    timestamp = doc.get("timestamp")
    if not isinstance(event_id, str):
        return None
    if not isinstance(component_id, str):
        component_id = "unknown"
    try:
        timestamp_value = float(timestamp)
    except (TypeError, ValueError):
        return None
    invocation_id = event_payload.get("operation_invocation_id")
    operation_id = event_payload.get("operation_id")
    operation_type = event_payload.get("operation_type")
    if not all(
        isinstance(value, str) and value
        for value in (invocation_id, operation_id, operation_type)
    ):
        return None
    encoded = (
        encoded_payload
        if encoded_payload is not None
        else json.dumps(doc, ensure_ascii=False, sort_keys=True)
    )
    values = _projection_values(
        event_id=event_id,
        event_type=event_type,
        timestamp=timestamp_value,
        component_id=component_id,
        context=context,
        payload=event_payload,
        encoded_payload=encoded,
    )
    return None if values is None else OperationInvocationProjection(values)


def event_operation_projection(event: NoetriumUnit) -> OperationInvocationProjection | None:
    return event_document_operation_projection(event_document(event))


def raw_event_operation_projection(payload: dict[str, object]) -> OperationInvocationProjection | None:
    return event_document_operation_projection(payload)


__all__ = [
    "OperationInvocationProjection",
    "event_document_operation_projection",
    "event_operation_projection",
    "raw_event_operation_projection",
]
