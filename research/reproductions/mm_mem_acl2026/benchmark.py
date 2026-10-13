from __future__ import annotations

BENCHMARK_SOURCES = {
    "video-mme": "https://video-mme.github.io/",
    "hd-epic": "https://github.com/hgaurav2k/HD-EPIC",
    "mlvu": "https://github.com/JUNJIE99/MLVU",
    "vstream-qa": "https://github.com/EliSpectre/MM-Mem",
}
BENCHMARK_IDS = tuple(sorted(BENCHMARK_SOURCES))


def require_paper_benchmark(benchmark_id: str) -> str:
    if benchmark_id not in BENCHMARK_SOURCES:
        raise ValueError(
            f"benchmark {benchmark_id!r} is outside mm_mem_acl2026 paper protocol; "
            f"expected one of {BENCHMARK_IDS!r}"
        )
    return BENCHMARK_SOURCES[benchmark_id]


__all__ = ["BENCHMARK_IDS", "BENCHMARK_SOURCES", "require_paper_benchmark"]
