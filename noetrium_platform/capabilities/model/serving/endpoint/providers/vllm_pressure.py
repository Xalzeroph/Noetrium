from __future__ import annotations

import math
import re
import time

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    AsyncTextHttpTransportPort,
    ModelEndpointRoute,
    ModelRuntimePressureSnapshot,
)


_METRIC = re.compile(
    r"^(vllm:[a-zA-Z0-9_]+)(?:\{[^}]*\})?\s+([-+0-9.eE]+)$"
)


def _metrics(text: str) -> dict[str, list[float]]:
    rows: dict[str, list[float]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _METRIC.fullmatch(line)
        if match is None:
            continue
        try:
            value = float(match.group(2))
        except ValueError:
            continue
        if not math.isfinite(value):
            continue
        rows.setdefault(match.group(1), []).append(value)
    return rows


def _sum_int(rows: dict[str, list[float]], name: str) -> int:
    return max(0, int(round(sum(rows.get(name, ())))))


def _max_float(rows: dict[str, list[float]], name: str) -> float:
    values = rows.get(name, ())
    return 0.0 if not values else max(0.0, min(1.0, max(values)))


class VllmRuntimePressureObserver:
    """Fail-isolated parser for vLLM's provider-specific Prometheus metrics."""

    def __init__(
        self,
        transport: AsyncTextHttpTransportPort,
        *,
        timeout_s: float = 2.0,
        clock=time.monotonic,
    ) -> None:
        if not isinstance(transport, AsyncTextHttpTransportPort):
            raise TypeError("vLLM pressure observer requires text HTTP transport")
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or not math.isfinite(float(timeout_s))
            or timeout_s <= 0
        ):
            raise ValueError("vLLM pressure timeout must be finite and positive")
        if not callable(clock):
            raise TypeError("vLLM pressure observer clock must be callable")
        self._transport = transport
        self._timeout_s = float(timeout_s)
        self._clock = clock

    async def snapshot(
        self,
        route: ModelEndpointRoute,
    ) -> ModelRuntimePressureSnapshot:
        if not isinstance(route, ModelEndpointRoute):
            raise TypeError("vLLM pressure snapshot requires ModelEndpointRoute")
        text = await self._transport.get_text(
            route.base_url.rstrip("/") + "/metrics",
            timeout_s=self._timeout_s,
        )
        rows = _metrics(text)
        queries = sum(rows.get("vllm:gpu_prefix_cache_queries_total", ()))
        hits = sum(rows.get("vllm:gpu_prefix_cache_hits_total", ()))
        hit_rate = None
        if queries > 0:
            hit_rate = max(0.0, min(1.0, hits / queries))
        prompt = _sum_int(rows, "vllm:prompt_tokens_total")
        generated = _sum_int(rows, "vllm:generation_tokens_total")
        return ModelRuntimePressureSnapshot(
            deployment_id=route.deployment_id,
            observed_monotonic=float(self._clock()),
            requests_running=_sum_int(rows, "vllm:num_requests_running"),
            requests_waiting=_sum_int(rows, "vllm:num_requests_waiting"),
            gpu_kv_cache_usage=_max_float(
                rows,
                "vllm:gpu_cache_usage_perc",
            ),
            preemptions_total=_sum_int(rows, "vllm:num_preemptions_total"),
            prefix_cache_hit_rate=hit_rate,
            prompt_tokens_total=prompt,
            generation_tokens_total=generated,
        )


__all__ = ["VllmRuntimePressureObserver"]
