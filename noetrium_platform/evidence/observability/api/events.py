from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.evidence.data.record.api import ExecutionRecordPlane


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """Storage-neutral structured event contract.

    Payloads should contain stable identities, digests, and bounded diagnostic fields;
    raw provider secrets and opaque implementation payloads do not belong here.
    Event ordering is a transport/storage concern; the envelope intentionally carries
    no caller-assigned sequence number.
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
        return asdict(self)


@runtime_checkable
class EventSink(Protocol):
    def append_event(self, event: EventEnvelope) -> object: ...


__all__ = ["EventEnvelope", "EventSink"]
