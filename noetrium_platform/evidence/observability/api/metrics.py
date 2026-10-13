from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import ExecutionContext


@dataclass(frozen=True, slots=True)
class ContextMetricObservation:
    name: str
    value: float
    dimensions: tuple[tuple[str, str], ...] = ()


@runtime_checkable
class ContextMetricSink(Protocol):
    def observe_many(
        self,
        context: ExecutionContext,
        observations: tuple[ContextMetricObservation, ...],
    ) -> object: ...

    def observe(
        self,
        context: ExecutionContext,
        name: str,
        value: float,
        **dimensions: str,
    ) -> object: ...


__all__ = ["ContextMetricObservation", "ContextMetricSink"]
