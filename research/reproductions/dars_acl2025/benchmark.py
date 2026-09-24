from __future__ import annotations
from noetrium.api import BenchmarkTaskSet

BENCHMARK_IDS = ("swe-bench",)

def require_dars_benchmark(benchmark: BenchmarkTaskSet, *, split_id: str) -> tuple:
    if benchmark.benchmark_id not in BENCHMARK_IDS:
        raise ValueError("dars benchmark identity is outside the paper protocol")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("dars benchmark split must contain tasks")
    return selected

__all__ = ["BENCHMARK_IDS", "require_dars_benchmark"]
