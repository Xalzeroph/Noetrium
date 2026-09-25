from __future__ import annotations
from noetrium.api import BenchmarkTaskSet

BENCHMARK_IDS = ("webarena",)

def require_webagent_r1_benchmark(benchmark: BenchmarkTaskSet, *, split_id: str) -> tuple:
    if benchmark.benchmark_id not in BENCHMARK_IDS:
        raise ValueError("webagent-r1 benchmark identity is outside the paper protocol")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("webagent-r1 benchmark split must contain tasks")
    return selected

__all__ = ["BENCHMARK_IDS", "require_webagent_r1_benchmark"]
