"""Unified publication renderer selecting a portable output backend."""
from __future__ import annotations

from ..api import FigureOutputFormat, FigureRendererPort, FigureSpec
from .pdf import PdfFigureRenderer
from .stdlib import SvgFigureRenderer


class PublicationFigureRenderer(FigureRendererPort):
    """Stable downstream facade: PDF by default, SVG on explicit request."""

    def __init__(self) -> None:
        self._pdf = PdfFigureRenderer()
        self._svg = SvgFigureRenderer()

    def render(
        self,
        figure: FigureSpec,
        *,
        output_format: FigureOutputFormat = FigureOutputFormat.PDF,
    ) -> str:
        if type(output_format) is not FigureOutputFormat:
            raise TypeError("output_format must be FigureOutputFormat")
        if output_format is FigureOutputFormat.PDF:
            return self._pdf.render(figure, output_format=output_format)
        if output_format is FigureOutputFormat.SVG:
            return self._svg.render(figure, output_format=output_format)
        raise ValueError(f"unsupported figure output format: {output_format}")
