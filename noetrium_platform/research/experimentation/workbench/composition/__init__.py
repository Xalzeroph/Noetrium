"""Composition entrypoints for the research workbench runtime."""

from ..api import ResearchStatisticsPort
from ..runtime import ScientificStatistics


def compose_standard_research_statistics() -> ResearchStatisticsPort:
    return ScientificStatistics()


__all__ = ["compose_standard_research_statistics"]
