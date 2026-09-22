from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable


class ExecutionRecordPlane(StrEnum):
    """Authority-neutral classification of execution records."""

    DURABLE_FACT = "durable_fact"
    LIVE_INTERCEPTION = "live_interception"
    SIDE_PLANE_OBSERVATION = "side_plane_observation"


@runtime_checkable
class RecordPlaneTagged(Protocol):
    @property
    def record_plane(self) -> ExecutionRecordPlane: ...


__all__ = ["ExecutionRecordPlane", "RecordPlaneTagged"]
