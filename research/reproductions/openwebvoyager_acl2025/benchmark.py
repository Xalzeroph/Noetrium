from __future__ import annotations
from noetrium_platform.research.experimentation.lifecycle.api import BenchmarkTaskSet

BENCHMARK_IDS = ("mind2web", "webvoyager")

def require_openwebvoyager_benchmark(benchmark: BenchmarkTaskSet, *, split_id: str) -> tuple:
    if benchmark.benchmark_id not in BENCHMARK_IDS:
        raise ValueError("openwebvoyager benchmark identity is outside the paper protocol")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("openwebvoyager benchmark split must contain tasks")
    return selected

__all__ = ["BENCHMARK_IDS", "require_openwebvoyager_benchmark"]
