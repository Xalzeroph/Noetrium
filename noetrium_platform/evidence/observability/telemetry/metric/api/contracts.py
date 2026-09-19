from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MetricKind(StrEnum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: str
    kind: MetricKind
    unit: str
    allowed_dimensions: tuple[str, ...]
    description: str

    def __post_init__(self) -> None:
        if not self.name or " " in self.name:
            raise ValueError("metric name must be non-empty and space-free")
        if len(set(self.allowed_dimensions)) != len(self.allowed_dimensions):
            raise ValueError(f"duplicate dimensions in metric {self.name}")


@dataclass(frozen=True, slots=True)
class MetricObservation:
    metric: str
    value: float
    timestamp: float
    dimensions: tuple[tuple[str, str], ...]


__all__ = ["MetricDefinition", "MetricKind", "MetricObservation"]
