from __future__ import annotations
BENCHMARK_SOURCES={
    "mmmu": "https://mmmu-benchmark.github.io/",
    "mathvista": "https://mathvista.github.io/",
    "mathvision": "https://mathllm.github.io/mathvision/",
    "hallusionbench": "https://github.com/tianyi-lab/HallusionBench",
    "mmstar": "https://github.com/MMStar-Benchmark/MMStar",
    "realworldqa": "https://huggingface.co/datasets/xai-org/RealworldQA",
}
BENCHMARK_IDS=tuple(sorted(BENCHMARK_SOURCES))
def require_paper_benchmark(benchmark_id:str)->str:
    if benchmark_id not in BENCHMARK_SOURCES:
        raise ValueError(f"benchmark {benchmark_id!r} is outside vilomem_cvpr2026 paper protocol; expected one of {BENCHMARK_IDS!r}")
    return BENCHMARK_SOURCES[benchmark_id]
__all__=["BENCHMARK_IDS","BENCHMARK_SOURCES","require_paper_benchmark"]
