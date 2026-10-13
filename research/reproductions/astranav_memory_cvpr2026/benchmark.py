from __future__ import annotations
BENCHMARK_SOURCES={
    "goat-bench": "https://github.com/Ram81/goat-bench",
    "hm3d-ovon": "https://github.com/facebookresearch/habitat-lab",
}
BENCHMARK_IDS=tuple(sorted(BENCHMARK_SOURCES))
def require_paper_benchmark(benchmark_id:str)->str:
    if benchmark_id not in BENCHMARK_SOURCES:
        raise ValueError(f"benchmark {benchmark_id!r} is outside astranav_memory_cvpr2026 paper protocol; expected one of {BENCHMARK_IDS!r}")
    return BENCHMARK_SOURCES[benchmark_id]
__all__=["BENCHMARK_IDS","BENCHMARK_SOURCES","require_paper_benchmark"]
