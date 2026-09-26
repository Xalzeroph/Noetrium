from __future__ import annotations

BENCHMARK_IDS = ("webarena",)

def require_r2d2_benchmark(benchmark, *, split_id: str) -> tuple:
    if benchmark.benchmark_id not in BENCHMARK_IDS:
        raise ValueError("r2d2 benchmark identity is outside the paper protocol")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("r2d2 benchmark split must contain tasks")
    return selected

__all__ = ["BENCHMARK_IDS", "require_r2d2_benchmark"]
