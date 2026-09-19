"""HuggingGPT paper-era task-cut authoring."""

from .cut import (
    HUGGINGGPT_BENCHMARK_ID,
    HUGGINGGPT_SOURCE_COMMIT,
    HUGGINGGPT_SPLIT_ID,
    HuggingGPTPaperTaskRecord,
    build_hugginggpt_paper_task_set,
)

__all__ = [
    "HUGGINGGPT_BENCHMARK_ID",
    "HUGGINGGPT_SOURCE_COMMIT",
    "HUGGINGGPT_SPLIT_ID",
    "HuggingGPTPaperTaskRecord",
    "build_hugginggpt_paper_task_set",
]
