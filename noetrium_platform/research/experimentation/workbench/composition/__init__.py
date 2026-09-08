"""Composition root for the standard-library research workbench."""

from dataclasses import dataclass

from ..api import FigureRendererPort, ReportTableRendererPort, TableReaderPort
from ..providers import (
    CsvTableReader,
    JsonlTableReader,
    PublicationFigureRenderer,
    StandardTableRenderer,
    SvgFigureRenderer,
)
from ..runtime import (
    ResearchFigureFactory,
    ResearchLifecycle,
    ScientificStatistics,
    TablePipeline,
)


@dataclass(frozen=True, slots=True)
class ResearchWorkbenchAssembly:
    lifecycle: ResearchLifecycle
    pipeline: TablePipeline
    statistics: ScientificStatistics
    figures: ResearchFigureFactory
    csv_reader: TableReaderPort
    jsonl_reader: TableReaderPort
    table_renderer: ReportTableRendererPort
    figure_renderer: FigureRendererPort
    svg_renderer: FigureRendererPort


def compose_standard_research_workbench() -> ResearchWorkbenchAssembly:
    pipeline = TablePipeline()
    statistics = ScientificStatistics()
    lifecycle = ResearchLifecycle(pipeline=pipeline, statistics=statistics)
    return ResearchWorkbenchAssembly(
        lifecycle=lifecycle,
        pipeline=pipeline,
        statistics=statistics,
        figures=ResearchFigureFactory(),
        csv_reader=CsvTableReader(),
        jsonl_reader=JsonlTableReader(),
        table_renderer=StandardTableRenderer(),
        figure_renderer=PublicationFigureRenderer(),
        svg_renderer=SvgFigureRenderer(),
    )


__all__ = ["ResearchWorkbenchAssembly", "compose_standard_research_workbench"]
