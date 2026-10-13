from __future__ import annotations
BENCHMARK_SOURCES={
    "mmbench-gui": "https://openaccess.thecvf.com/content/CVPR2026/html/Wang_MMBench-GUI_A_Unified_Hierarchical_Evaluation_Framework_for_Multi-Platform_GUI_Agents_CVPR_2026_paper.html",
}
BENCHMARK_IDS=tuple(sorted(BENCHMARK_SOURCES))
def require_paper_benchmark(benchmark_id:str)->str:
    if benchmark_id not in BENCHMARK_SOURCES:
        raise ValueError(f"benchmark {benchmark_id!r} is outside mmbench_gui_cvpr2026 paper protocol; expected one of {BENCHMARK_IDS!r}")
    return BENCHMARK_SOURCES[benchmark_id]
__all__=["BENCHMARK_IDS","BENCHMARK_SOURCES","require_paper_benchmark"]
