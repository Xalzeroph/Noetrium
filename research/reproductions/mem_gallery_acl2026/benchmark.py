from __future__ import annotations

BENCHMARK_SOURCES = {
    "mem-gallery": "https://github.com/YuanchenBei/Mem-Gallery",
}
BENCHMARK_IDS = tuple(sorted(BENCHMARK_SOURCES))


def require_paper_benchmark(benchmark_id: str) -> str:
    if benchmark_id not in BENCHMARK_SOURCES:
        raise ValueError(
            f"benchmark {benchmark_id!r} is outside mem_gallery_acl2026 paper protocol; "
            f"expected one of {BENCHMARK_IDS!r}"
        )
    return BENCHMARK_SOURCES[benchmark_id]


__all__ = ["BENCHMARK_IDS", "BENCHMARK_SOURCES", "require_paper_benchmark"]
