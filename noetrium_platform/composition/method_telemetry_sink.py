from __future__ import annotations

from noetrium_platform.capabilities.participant.method.api import MethodObservation
from noetrium_platform.evidence.observability.capture.api import RawObservationReceipt
from noetrium_platform.evidence.observability.capture.runtime import RawObservationLake


class RawLakeMethodObservationSink:
    def __init__(self, lake: RawObservationLake) -> None:
        self.lake = lake

    def record(self, observation: MethodObservation) -> RawObservationReceipt:
        return self.lake.append_once(
            observation.context,
            "method.raw",
            {
                "method": observation.method_id,
                "kind": observation.kind,
                "session_id": observation.session_id,
                "observation_id": observation.observation_id,
                **dict(observation.payload),
            },
            idempotency_key=observation.observation_id,
        )
