from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol, runtime_checkable

from .contracts import ModelEndpointRoute


@dataclass(frozen=True, slots=True)
class ModelRuntimePressureSnapshot:
    deployment_id: str
    observed_monotonic: float
    requests_running: int
    requests_waiting: int
    gpu_kv_cache_usage: float
    preemptions_total: int
    prefix_cache_hit_rate: float | None = None
    prompt_tokens_total: int | None = None
    generation_tokens_total: int | None = None

    def __post_init__(self) -> None:
        if type(self.deployment_id) is not str or not self.deployment_id.strip():
            raise ValueError("model runtime pressure deployment_id is required")
        if (
            isinstance(self.observed_monotonic, bool)
            or not isinstance(self.observed_monotonic, (int, float))
            or not math.isfinite(float(self.observed_monotonic))
            or self.observed_monotonic < 0
        ):
            raise ValueError("model runtime pressure observed_monotonic must be finite")
        for name in (
            "requests_running",
            "requests_waiting",
            "preemptions_total",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"model runtime pressure {name} must be non-negative integer")
        if (
            isinstance(self.gpu_kv_cache_usage, bool)
            or not isinstance(self.gpu_kv_cache_usage, (int, float))
            or not math.isfinite(float(self.gpu_kv_cache_usage))
            or not 0.0 <= float(self.gpu_kv_cache_usage) <= 1.0
        ):
            raise ValueError("model runtime pressure gpu_kv_cache_usage must be in [0,1]")
        if self.prefix_cache_hit_rate is not None and (
            isinstance(self.prefix_cache_hit_rate, bool)
            or not isinstance(self.prefix_cache_hit_rate, (int, float))
            or not math.isfinite(float(self.prefix_cache_hit_rate))
            or not 0.0 <= float(self.prefix_cache_hit_rate) <= 1.0
        ):
            raise ValueError("model runtime pressure prefix_cache_hit_rate must be in [0,1]")
        for name in ("prompt_tokens_total", "generation_tokens_total"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"model runtime pressure {name} must be non-negative integer or None")


@runtime_checkable
class ModelRuntimePressureObserverPort(Protocol):
    async def snapshot(
        self,
        route: ModelEndpointRoute,
    ) -> ModelRuntimePressureSnapshot: ...


__all__ = [
    "ModelRuntimePressureObserverPort",
    "ModelRuntimePressureSnapshot",
]
