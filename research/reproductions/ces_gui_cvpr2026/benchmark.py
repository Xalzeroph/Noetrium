from __future__ import annotations
BENCHMARK_SOURCES={
    "aitz": "https://github.com/IMNearth/Android-In-The-Zoo",
    "amex": "https://github.com/hehehahi4/CES",
    "gui-odyssey": "https://github.com/OpenGVLab/GUI-Odyssey",
}
BENCHMARK_IDS=tuple(sorted(BENCHMARK_SOURCES))
def require_paper_benchmark(benchmark_id:str)->str:
    if benchmark_id not in BENCHMARK_SOURCES:
        raise ValueError(f"benchmark {benchmark_id!r} is outside ces_gui_cvpr2026 paper protocol; expected one of {BENCHMARK_IDS!r}")
    return BENCHMARK_SOURCES[benchmark_id]
__all__=["BENCHMARK_IDS","BENCHMARK_SOURCES","require_paper_benchmark"]
