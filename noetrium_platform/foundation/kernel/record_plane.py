from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import time
from typing import Protocol, runtime_checkable

from .kernel.context import ExecutionContext


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
        return asdict(self)


@runtime_checkable
class EventSink(Protocol):
    def append_event(self, event: EventEnvelope) -> object: ...


__all__ = [
    "EventEnvelope",
    "EventSink",
    "ExecutionRecordPlane",
    "RecordPlaneTagged",
]
