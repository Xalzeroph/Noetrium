from __future__ import annotations

BENCHMARK_SOURCES = {
    "osworld-verified": "https://github.com/xlang-ai/OSWorld",
    "windowsagentarena": "https://github.com/microsoft/WindowsAgentArena",
    "macosarena": "https://github.com/OS-Copilot/OS-Symphony",
}
BENCHMARK_IDS = tuple(sorted(BENCHMARK_SOURCES))


def require_paper_benchmark(benchmark_id: str) -> str:
    if benchmark_id not in BENCHMARK_SOURCES:
        raise ValueError(
            f"benchmark {benchmark_id!r} is outside os_symphony_acl2026 paper protocol; "
            f"expected one of {BENCHMARK_IDS!r}"
        )
    return BENCHMARK_SOURCES[benchmark_id]


__all__ = ["BENCHMARK_IDS", "BENCHMARK_SOURCES", "require_paper_benchmark"]
