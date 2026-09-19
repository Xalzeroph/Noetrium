from __future__ import annotations

from threading import RLock
import time

from noetrium_platform.evidence.observability.api.emission import operational_observation_enabled

from ..api.contracts import MetricObservation
from .registry import MetricRegistry


class InMemoryMetricRecorder:
    def __init__(self, registry: MetricRegistry) -> None:
        self.registry = registry
        self._rows: list[MetricObservation] = []
        self._lock = RLock()

    def observe(self, name: str, value: float, **dimensions: str) -> None:
        if not operational_observation_enabled():
            return
        numeric = self.registry.validate_observation(name, value, dimensions)
        row = MetricObservation(name, numeric, time.time(), tuple(sorted(dimensions.items())))
        with self._lock:
            self._rows.append(row)

    def rows(self) -> tuple[MetricObservation, ...]:
        with self._lock:
            return tuple(self._rows)


__all__ = ["InMemoryMetricRecorder"]
