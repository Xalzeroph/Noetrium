from __future__ import annotations
BENCHMARK_SOURCES={
    "screenspot-pro": "https://github.com/likaixin2000/ScreenSpot-Pro-GUI-Grounding",
    "screenspot-v2": "https://github.com/njucckevin/ScreenSpot",
    "androidcontrol": "https://github.com/google-research/google-research/tree/master/android_control",
}
BENCHMARK_IDS=tuple(sorted(BENCHMARK_SOURCES))
def require_paper_benchmark(benchmark_id:str)->str:
    if benchmark_id not in BENCHMARK_SOURCES:
        raise ValueError(f"benchmark {benchmark_id!r} is outside ui_agile_cvprf2026 paper protocol; expected one of {BENCHMARK_IDS!r}")
    return BENCHMARK_SOURCES[benchmark_id]
__all__=["BENCHMARK_IDS","BENCHMARK_SOURCES","require_paper_benchmark"]
