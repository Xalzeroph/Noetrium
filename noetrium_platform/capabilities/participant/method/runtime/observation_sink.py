from __future__ import annotations
from threading import RLock
from noetrium_platform.capabilities.participant.method.api.observability import MethodObservation

class InMemoryMethodObservationSink:
    def __init__(self) -> None:
        self._rows: list[MethodObservation] = []
        self._ids: set[str] = set()
        self._lock = RLock()

    def record(self, observation: MethodObservation) -> int:
        with self._lock:
            if observation.observation_id in self._ids:
                return next(i for i, row in enumerate(self._rows, 1) if row.observation_id == observation.observation_id)
            self._rows.append(observation)
            self._ids.add(observation.observation_id)
            return len(self._rows)

    def rows(self) -> tuple[MethodObservation, ...]:
        with self._lock:
            return tuple(self._rows)

__all__=["InMemoryMethodObservationSink"]
