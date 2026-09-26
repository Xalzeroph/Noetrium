from __future__ import annotations

BENCHMARK_IDS = ("visualwebarena", "webarena")

def require_contextual_experience_replay_benchmark(benchmark, *, split_id: str) -> tuple:
    if benchmark.benchmark_id not in BENCHMARK_IDS:
        raise ValueError("contextual-experience-replay benchmark identity is outside the paper protocol")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("contextual-experience-replay benchmark split must contain tasks")
    return selected

__all__ = ["BENCHMARK_IDS", "require_contextual_experience_replay_benchmark"]
