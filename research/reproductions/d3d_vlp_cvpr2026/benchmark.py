from __future__ import annotations
BENCHMARK_SOURCES={
    "r2r-ce": "https://github.com/facebookresearch/habitat-lab",
    "reverie-ce": "https://github.com/YicongHong/Recurrent-VLN-BERT",
    "navrag-ce": "https://github.com/MrZihan/D3D-VLP",
    "hm3d-ovon": "https://github.com/facebookresearch/habitat-lab",
    "sg3d": "https://github.com/MrZihan/D3D-VLP",
}
BENCHMARK_IDS=tuple(sorted(BENCHMARK_SOURCES))
def require_paper_benchmark(benchmark_id:str)->str:
    if benchmark_id not in BENCHMARK_SOURCES:
        raise ValueError(f"benchmark {benchmark_id!r} is outside d3d_vlp_cvpr2026 paper protocol; expected one of {BENCHMARK_IDS!r}")
    return BENCHMARK_SOURCES[benchmark_id]
__all__=["BENCHMARK_IDS","BENCHMARK_SOURCES","require_paper_benchmark"]
