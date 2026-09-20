from __future__ import annotations
BENCHMARK_SOURCES={
    "aitw": "https://github.com/google-research/google-research/tree/master/android_in_the_wild",
    "androidcontrol": "https://github.com/google-research/google-research/tree/master/android_control",
    "gui-odyssey": "https://github.com/OpenGVLab/GUI-Odyssey",
    "guiact": "https://github.com/xc-li/GUIAct",
}
BENCHMARK_IDS=tuple(sorted(BENCHMARK_SOURCES))
def require_paper_benchmark(benchmark_id:str)->str:
    if benchmark_id not in BENCHMARK_SOURCES:
        raise ValueError(f"benchmark {benchmark_id!r} is outside ishift_cvpr2026 paper protocol; expected one of {BENCHMARK_IDS!r}")
    return BENCHMARK_SOURCES[benchmark_id]
__all__=["BENCHMARK_IDS","BENCHMARK_SOURCES","require_paper_benchmark"]
