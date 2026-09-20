from __future__ import annotations
from noetrium_platform.research.experimentation.study.api import BenchmarkTaskSet

BENCHMARK_IDS = ("osworld",)

def require_watch_and_learn_benchmark(benchmark: BenchmarkTaskSet, *, split_id: str) -> tuple:
    if benchmark.benchmark_id not in BENCHMARK_IDS:
        raise ValueError("watch-and-learn benchmark identity is outside the paper protocol")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("watch-and-learn benchmark split must contain tasks")
    return selected

__all__ = ["BENCHMARK_IDS", "require_watch_and_learn_benchmark"]
