"""FreshWiki paper-era evaluation cut."""

from .cut import (
    FRESHWIKI_BENCHMARK_ID,
    FRESHWIKI_PAPER_TASK_COUNT,
    FRESHWIKI_SPLIT_ID,
    FreshWikiTopicRecord,
    build_freshwiki_task_set,
)

__all__ = [
    "FRESHWIKI_BENCHMARK_ID",
    "FRESHWIKI_PAPER_TASK_COUNT",
    "FRESHWIKI_SPLIT_ID",
    "FreshWikiTopicRecord",
    "build_freshwiki_task_set",
]
