from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable


class ExecutionRecordPlane(StrEnum):
    """Semantic plane of a runtime record.

    DURABLE_FACT may participate in deterministic reconstruction/replay.
    LIVE_INTERCEPTION may affect only the current execution and must leave a
    durable fact when it changes model-visible or side-effecting behavior.
    SIDE_PLANE_OBSERVATION is diagnostic/telemetry output and must never be used
    as primary operational or scientific authority.
    """

    DURABLE_FACT = "durable_fact"
    LIVE_INTERCEPTION = "live_interception"
    SIDE_PLANE_OBSERVATION = "side_plane_observation"


@runtime_checkable
class RecordPlaneTagged(Protocol):
    @property
    def record_plane(self) -> ExecutionRecordPlane: ...


__all__ = ["ExecutionRecordPlane", "RecordPlaneTagged"]
