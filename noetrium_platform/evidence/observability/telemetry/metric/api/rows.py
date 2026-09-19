from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import ExecutionContext


@dataclass(frozen=True, slots=True)
class ContextualMetricRow:
    sequence: int
    metric: str
    value: float
    timestamp: float
    context: ExecutionContext
    dimensions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class PendingMetric:
    context: ExecutionContext
    metric: str
    value: float
    timestamp: float
    dimensions: tuple[tuple[str, str], ...]


__all__ = ["ContextualMetricRow", "PendingMetric"]
