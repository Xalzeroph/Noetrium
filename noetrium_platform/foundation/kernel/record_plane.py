from __future__ import annotations

from enum import StrEnum
import time
from typing import Mapping, Protocol, runtime_checkable

from .event import causal_event, event_field, event_ref_digest, is_event_unit
from .kernel.context import ExecutionContext, execution_context_payload
from .kernel.canonical import canonical_bytes, canonical_digest, thaw_json
from .truth import TruthModality
from .unit import NoetriumUnit
from .unit_codec import decode_unit, unit_document


class ExecutionRecordPlane(StrEnum):
    """Authority-neutral classification of execution records."""

    LIVE_INTERCEPTION = "live_interception"
    SIDE_PLANE_OBSERVATION = "side_plane_observation"


@runtime_checkable
class RecordPlaneTagged(Protocol):
    @property
    def record_plane(self) -> ExecutionRecordPlane: ...


def event_record(
    event_id: str,
    event_type: str,
    context: ExecutionContext,
    component_id: str,
    payload: dict[str, object] | None = None,
    timestamp: float | None = None,
    artifact_refs: tuple[str, ...] = (),
    state_refs: tuple[str, ...] = (),
    effect_refs: tuple[str, ...] = (),
    request_refs: tuple[str, ...] = (),
) -> NoetriumUnit:
    """Create one observed execution Event on the universal carrier."""

    if type(event_id) is not str or not event_id.strip():
        raise ValueError("execution event_id must be non-empty")
    if type(event_type) is not str or not event_type.strip():
        raise ValueError("execution event_type must be non-empty")
    if type(component_id) is not str or not component_id.strip():
        raise ValueError("execution event component_id must be non-empty")
    context_payload = thaw_json(execution_context_payload(context))
    observed_at = time.time() if timestamp is None else float(timestamp)
    attributes = {
        "event_id": event_id,
        "event_type": event_type,
        "context": context_payload,
        "component_id": component_id,
        "timestamp": observed_at,
        "payload": {} if payload is None else payload,
        "artifact_refs": tuple(artifact_refs),
        "state_refs": tuple(state_refs),
        "effect_refs": tuple(effect_refs),
        "request_refs": tuple(request_refs),
    }
    return causal_event(
        authority_domain=(
            "execution."
            + canonical_digest((context.run_id, component_id))[:32]
        ),
        generation=0,
        subject=f"execution:{event_id}",
        operation="record",
        phase="observed",
        modality=TruthModality.OBSERVED,
        reads=tuple(
            sorted(
                {
                    *(f"state:{ref}" for ref in state_refs),
                    *(f"effect:{ref}" for ref in effect_refs),
                    *(f"request:{ref}" for ref in request_refs),
                }
            )
        ),
        evidence=(),
        event_kind="execution.event",
        attributes=attributes,
    )


def event_document(event: NoetriumUnit) -> dict[str, object]:
    """Lossless stable projection of any causal Event Unit."""

    if not is_event_unit(event):
        raise TypeError("forensic event must be system.event NoetriumUnit")
    attributes = event_field(event, "event_attributes")
    if not isinstance(attributes, Mapping):
        raise TypeError("forensic event attributes must be an object")

    if all(
        name in attributes
        for name in (
            "event_id",
            "event_type",
            "context",
            "component_id",
            "timestamp",
            "payload",
        )
    ):
        event_id = str(attributes["event_id"])
        event_type = str(attributes["event_type"])
        context = thaw_json(attributes["context"])
        component_id = str(attributes["component_id"])
        timestamp = float(attributes["timestamp"])
        payload = thaw_json(attributes["payload"])
        artifact_refs = tuple(attributes.get("artifact_refs", ()))
        state_refs = tuple(attributes.get("state_refs", ()))
        effect_refs = tuple(attributes.get("effect_refs", ()))
        request_refs = tuple(attributes.get("request_refs", ()))
    elif event.has_schema("reliability.failure"):
        failure_id = str(attributes["failure_id"])
        event_id = "event_failure_" + failure_id
        event_type = "FAILURE_RECORDED"
        context = thaw_json(attributes["context"])
        component_id = str(attributes["component_id"])
        timestamp = float(attributes["created_at"])
        payload = {
            "failure_id": failure_id,
            "operation_id": attributes.get("operation_id"),
            "operation_invocation_id": attributes.get(
                "operation_invocation_id"
            ),
            "domain": attributes.get("failure_domain"),
            "code": attributes.get("failure_code"),
            "stage": attributes.get("stage"),
        }
        artifact_refs = tuple(attributes.get("input_artifacts", ())) + tuple(
            attributes.get("output_artifacts", ())
        )
        state_refs = tuple(attributes.get("state_refs", ()))
        effect_refs = tuple(attributes.get("effect_refs", ()))
        request_refs = tuple(attributes.get("request_refs", ()))
    else:
        # Generic Event projection. Domain-specific indexers may ignore it, but
        # the authoritative ledger remains lossless and fully reconstructable.
        event_id = "event_" + event.unit_digest
        event_type = str(event_field(event, "operation")).upper()
        context = {}
        component_id = str(event_field(event, "authority_domain"))
        timestamp = float(attributes.get("timestamp", 0.0))
        payload = {
            "phase": event_field(event, "phase"),
            "truth_modality": event_field(event, "modality").value,
            "attributes": thaw_json(attributes),
        }
        artifact_refs = ()
        state_refs = ()
        effect_refs = ()
        request_refs = ()

    return {
        "event_id": event_id,
        "event_type": event_type,
        "context": context,
        "component_id": component_id,
        "timestamp": timestamp,
        "payload": payload,
        "artifact_refs": artifact_refs,
        "state_refs": state_refs,
        "effect_refs": effect_refs,
        "request_refs": request_refs,
        "event_digest": event.unit_digest,
        "causal_event_refs": tuple(
            digest
            for reference in event_field(event, "causal_parents")
            if (digest := event_ref_digest(reference)) is not None
        ),
        "unit_document": thaw_json(unit_document(event)),
    }


def event_from_document(document: Mapping[str, object]) -> NoetriumUnit:
    """Recover the exact Event Unit from its forensic ledger projection."""

    if not isinstance(document, Mapping):
        raise TypeError("execution event document must be an object")
    raw = document.get("unit_document")
    if not isinstance(raw, Mapping):
        raise ValueError("execution event document lacks canonical Unit document")
    event = decode_unit(canonical_bytes(raw))
    if not is_event_unit(event):
        raise ValueError("forensic event document decoded a non-event Unit")
    if document.get("event_digest") != event.unit_digest:
        raise ValueError("execution event document digest mismatch")
    return event


@runtime_checkable
class EventSink(Protocol):
    def append_event(self, event: NoetriumUnit) -> object: ...


__all__ = [
    "event_document",
    "event_from_document",
    "event_record",
    "EventSink",
    "ExecutionRecordPlane",
    "RecordPlaneTagged",
]
