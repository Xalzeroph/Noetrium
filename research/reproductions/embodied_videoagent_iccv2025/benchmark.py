from __future__ import annotations
from noetrium_platform.research.experimentation.study.api import BenchmarkTaskSet

BENCHMARK_IDS = ("open-eqa", "envqa", "ego4d-vq3d")

def require_embodied_videoagent_benchmark(benchmark: BenchmarkTaskSet, *, split_id: str) -> tuple:
    if benchmark.benchmark_id not in BENCHMARK_IDS:
        raise ValueError("embodied-videoagent benchmark identity is outside the paper protocol")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("embodied-videoagent benchmark split must contain tasks")
    return selected

__all__ = ["BENCHMARK_IDS", "require_embodied_videoagent_benchmark"]
