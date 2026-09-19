"""ScreenSpot GUI grounding benchmark cut."""

from .cut import (
    SCREENSPOT_BENCHMARK_ID,
    SCREENSPOT_ELEMENT_TYPES,
    SCREENSPOT_PLATFORMS,
    SCREENSPOT_SPLIT_ID,
    ScreenSpotRecord,
    build_screenspot_task_set,
)

__all__ = [
    "SCREENSPOT_BENCHMARK_ID",
    "SCREENSPOT_ELEMENT_TYPES",
    "SCREENSPOT_PLATFORMS",
    "SCREENSPOT_SPLIT_ID",
    "ScreenSpotRecord",
    "build_screenspot_task_set",
]
