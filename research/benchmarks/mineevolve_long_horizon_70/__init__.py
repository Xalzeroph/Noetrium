from functools import lru_cache
from pathlib import Path
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from research.benchmarks._native_minecraft import build_native_minecraft_cut

BENCHMARK_ID = 'mineevolve-long-horizon-70'

@lru_cache(maxsize=1)
def build_native_cut() -> NoetriumUnit:
    cut = build_native_minecraft_cut(Path(__file__).with_name("native_cut.json"))
    if cut.unit_id != BENCHMARK_ID:
        raise ValueError("native benchmark identity drifted")
    return cut

__all__ = ["BENCHMARK_ID", "build_native_cut"]
