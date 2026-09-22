from __future__ import annotations
from noetrium_platform.research.experimentation.lifecycle.api import BenchmarkTaskSet

BENCHMARK_IDS = ("egoschema",)

def require_videoarm_benchmark(benchmark: BenchmarkTaskSet, *, split_id: str) -> tuple:
    if benchmark.benchmark_id not in BENCHMARK_IDS:
        raise ValueError("videoarm benchmark identity is outside the paper protocol")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("videoarm benchmark split must contain tasks")
    return selected

__all__ = ["BENCHMARK_IDS", "require_videoarm_benchmark"]
