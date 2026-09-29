from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time
from typing import Protocol, runtime_checkable

from .kernel.context import ExecutionContext, execution_context_payload
from .kernel.canonical import freeze_json, thaw_json


class ExecutionRecordPlane(StrEnum):
    """Authority-neutral classification of execution records."""

    DURABLE_FACT = "durable_fact"
    LIVE_INTERCEPTION = "live_interception"
    SIDE_PLANE_OBSERVATION = "side_plane_observation"


@runtime_checkable
class RecordPlaneTagged(Protocol):
    @property
    def record_plane(self) -> ExecutionRecordPlane: ...


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """Kernel ABI for one immutable side-plane execution observation.

    The envelope owns no logging, tracing, storage, indexing, or diagnostic semantics.
    Those belong to higher authorities. This type exists only so independent systems
    can exchange an observation record without depending on one another.
    """

    event_id: str
    event_type: str
    context: ExecutionContext
    component_id: str
    timestamp: float = field(default_factory=time.time)
    payload: dict[str, object] = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()
    state_refs: tuple[str, ...] = ()
    effect_refs: tuple[str, ...] = ()
    request_refs: tuple[str, ...] = ()

    @property
    def record_plane(self) -> ExecutionRecordPlane:
        return ExecutionRecordPlane.SIDE_PLANE_OBSERVATION

    def to_dict(self) -> dict[str, object]:
        # ExecutionContext owns frozen JSON objects backed by mappingproxy.
        # dataclasses.asdict() deep-copies them and therefore fails. Serialize
        # through the kernel-owned canonical codecs instead of object copying.
        payload = thaw_json(freeze_json(self.payload))
        if not isinstance(payload, dict):
            raise TypeError("event payload must encode to an object")
        context = thaw_json(execution_context_payload(self.context))
        if not isinstance(context, dict):
            raise TypeError("event context must encode to an object")
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "context": context,
            "component_id": self.component_id,
            "timestamp": self.timestamp,
            "payload": payload,
            "artifact_refs": self.artifact_refs,
            "state_refs": self.state_refs,
            "effect_refs": self.effect_refs,
            "request_refs": self.request_refs,
        }


@runtime_checkable
class EventSink(Protocol):
    def append_event(self, event: EventEnvelope) -> object: ...


__all__ = [
    "EventEnvelope",
    "EventSink",
    "ExecutionRecordPlane",
    "RecordPlaneTagged",
]
