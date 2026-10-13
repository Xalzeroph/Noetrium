from __future__ import annotations
BENCHMARK_SOURCES={
    "scienceworld": "https://github.com/allenai/ScienceWorld",
    "alfworld": "https://github.com/alfworld/alfworld",
    "webshop": "https://github.com/princeton-nlp/WebShop",
}
BENCHMARK_IDS=tuple(sorted(BENCHMARK_SOURCES))
def require_paper_benchmark(benchmark_id:str)->str:
    if benchmark_id not in BENCHMARK_SOURCES:
        raise ValueError(f"benchmark {benchmark_id!r} is outside eaglet_acl2026 paper protocol; expected one of {BENCHMARK_IDS!r}")
    return BENCHMARK_SOURCES[benchmark_id]
__all__=["BENCHMARK_IDS","BENCHMARK_SOURCES","require_paper_benchmark"]
