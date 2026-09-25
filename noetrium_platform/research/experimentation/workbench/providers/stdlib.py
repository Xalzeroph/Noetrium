"""Portable standard-library providers; heavier scientific backends remain optional adapters."""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import math
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import canonical_digest, thaw_json
from ..api import (
    DataColumn, DataTable, FigureKind, FigureOutputFormat, FigureSpec, FigureRendererPort,
    ReportTableRendererPort, StudyObservationTableAdapter, MeasurementRecordTableAdapter,
    TableReaderPort,
)


def _parse_cell(value: str, coerce_numeric: bool):
    if not coerce_numeric:
        return value
    stripped = value.strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(stripped)
    except ValueError:
        try:
            number = float(stripped)
        except ValueError:
            return value
        return number if math.isfinite(number) else value


class CsvTableReader(TableReaderPort):
    def __init__(self, *, delimiter: str = ",", coerce_numeric: bool = False) -> None:
        if len(delimiter) != 1:
            raise ValueError("CSV delimiter must be one character")
        self._delimiter = delimiter
        self._coerce_numeric = coerce_numeric

    def read(self, source: str, *, table_id: str) -> DataTable:
        path = Path(source)
        payload = path.read_bytes()
        text = payload.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text), delimiter=self._delimiter))
        if not rows:
            raise ValueError("CSV source must contain a header")
        header = tuple(rows[0])
        if not header or any(not name.strip() for name in header):
            raise ValueError("CSV header names must be non-empty")
        if len(set(header)) != len(header):
            raise ValueError("CSV header names must be unique")
        width = len(header)
        values = tuple(tuple(_parse_cell(value, self._coerce_numeric) for value in row) for row in rows[1:])
        if any(len(row) != width for row in values):
            raise ValueError("CSV row width does not match header")
        columns = tuple(DataColumn(name, "unknown", True) for name in header)
        return DataTable(table_id, columns, values, source_digest=hashlib.sha256(payload).hexdigest(),
                         metadata=(("source_format", "csv"),))


class JsonlTableReader(TableReaderPort):
    def read(self, source: str, *, table_id: str) -> DataTable:
        path = Path(source)
        payload = path.read_bytes()
        records = [json.loads(line) for line in payload.decode("utf-8-sig").splitlines() if line.strip()]
        if not records or any(type(record) is not dict for record in records):
            raise ValueError("JSONL source must contain non-empty object records")
        names = tuple(sorted({name for record in records for name in record}))
        columns = tuple(DataColumn(name, "unknown", True) for name in names)
        rows = tuple(tuple(record.get(name) for name in names) for record in records)
        return DataTable(table_id, columns, rows, source_digest=hashlib.sha256(payload).hexdigest(),
                         metadata=(("source_format", "jsonl"),))


def _cell(value: object) -> str:
    return json.dumps(thaw_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")) if isinstance(value, (dict, list, tuple)) else str(value)


class StandardTableRenderer(ReportTableRendererPort):
    def render(self, table: DataTable, format: str) -> str:
        format = format.lower()
        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(table.column_names)
            writer.writerows((_cell(value) for value in row) for row in table.rows)
            return output.getvalue()
        if format == "markdown":
            head = "| " + " | ".join(table.column_names) + " |"
            rule = "| " + " | ".join("---" for _ in table.columns) + " |"
            body = "\n".join("| " + " | ".join(_cell(value).replace("|", "\\|") for value in row) + " |" for row in table.rows)
            return "\n".join((head, rule, body))
        if format in {"latex", "tex"}:
            body = "\n".join(" & ".join(_cell(value).replace("&", "\\&") for value in row) + r" \\" for row in table.rows)
            return "\n".join((r"\begin{tabular}{" + "l" * len(table.columns) + "}", " & ".join(table.column_names) + r" \\", body, r"\end{tabular}"))
        raise ValueError("table format must be csv, markdown, or latex")


class SvgFigureRenderer(FigureRendererPort):
    """Deterministic SVG output for paper figures without requiring matplotlib."""

    @staticmethod
    def _quantile(values: list[float], probability: float) -> float:
        ordered = sorted(values)
        position = (len(ordered) - 1) * probability
        lower, upper = math.floor(position), math.ceil(position)
        if lower == upper:
            return ordered[lower]
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    @staticmethod
    def _grid_elements(style, left: float, top: float, plot_w: float, plot_h: float) -> tuple[str, ...]:
        if not style.show_grid:
            return ()
        lines = []
        for step in range(1, 5):
            y = top + plot_h * step / 5.0
            x = left + plot_w * step / 5.0
            lines.append(f'<line x1="{left:.2f}" y1="{y:.2f}" x2="{left + plot_w:.2f}" y2="{y:.2f}" stroke="{style.grid}" stroke-width="0.8"/>')
            lines.append(f'<line x1="{x:.2f}" y1="{top:.2f}" x2="{x:.2f}" y2="{top + plot_h:.2f}" stroke="{style.grid}" stroke-width="0.8"/>')
        return tuple(lines)

    def _render_heatmap(self, figure: FigureSpec) -> str:
        width, height = figure.width, figure.height
        style = figure.style
        background = "none" if style.transparent else style.background
        font = html.escape(style.font_family, quote=True)
        left, top, right, bottom = 72, 48, 28, 64
        plot_w, plot_h = width - left - right, height - top - bottom
        rows = sorted({repr(cell.row) for cell in figure.cells})
        columns = sorted({repr(cell.column) for cell in figure.cells})
        values = {(repr(cell.row), repr(cell.column)): float(cell.value) for cell in figure.cells}
        low, high = min(values.values()), max(values.values())
        span = high - low or 1.0
        cell_w, cell_h = plot_w / max(len(columns), 1), plot_h / max(len(rows), 1)
        elements = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            f'<rect width="{width}" height="{height}" fill="{background}"/>',
            f'<text x="{width / 2}" y="24" text-anchor="middle" font-family="{font}" font-size="{style.title_size}" font-weight="600" fill="{style.foreground}">{html.escape(figure.title)}</text>',
        ]
        elements.extend(self._grid_elements(style, left, top, plot_w, plot_h))
        for row_index, row in enumerate(rows):
            for column_index, column in enumerate(columns):
                value = values.get((row, column))
                if value is None:
                    continue
                intensity = (value - low) / span
                red = int(37 + 190 * intensity)
                blue = int(235 - 170 * intensity)
                color = f"rgb({red},80,{blue})"
                elements.append(f'<rect x="{left + column_index * cell_w:.2f}" y="{top + row_index * cell_h:.2f}" width="{cell_w:.2f}" height="{cell_h:.2f}" fill="{color}"/>')
                elements.append(f'<text x="{left + (column_index + .5) * cell_w:.2f}" y="{top + (row_index + .6) * cell_h:.2f}" text-anchor="middle" font-family="{font}" font-size="{style.tick_size}" fill="{style.foreground}">{value:g}</text>')
        elements.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="none" stroke="{style.foreground}"/>')
        elements.append(f'<text x="{width / 2}" y="{height - 18}" text-anchor="middle" font-family="{font}" font-size="{style.label_size}" fill="{style.foreground}">{html.escape(figure.x_label)}</text>')
        elements.append(f'<text x="16" y="{height / 2}" transform="rotate(-90 16 {height / 2})" text-anchor="middle" font-family="{font}" font-size="{style.label_size}" fill="{style.foreground}">{html.escape(figure.y_label)}</text>')
        if figure.caption:
            elements.append(f'<text x="{left}" y="{height - 4}" font-family="{font}" font-size="{style.tick_size}" fill="{style.foreground}">{html.escape(figure.caption)}</text>')
        elements.append("</svg>")
        return "".join(elements)

    def _render_boxplot(self, figure: FigureSpec) -> str:
        width, height = figure.width, figure.height
        style = figure.style
        background = "none" if style.transparent else style.background
        font = html.escape(style.font_family, quote=True)
        left, top, right, bottom = 72, 48, 28, 64
        plot_w, plot_h = width - left - right, height - top - bottom
        values = [float(point.y) for series in figure.series for point in series.points]
        ymin, ymax = min(0.0, min(values)), max(0.0, max(values))
        if math.isclose(ymin, ymax):
            ymax = ymin + 1.0

        def y_pos(value: float) -> float:
            return top + plot_h * (ymax - value) / (ymax - ymin)

        elements = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            f'<rect width="{width}" height="{height}" fill="{background}"/>',
            f'<text x="{width / 2}" y="24" text-anchor="middle" font-family="{font}" font-size="{style.title_size}" font-weight="600" fill="{style.foreground}">{html.escape(figure.title)}</text>',
            f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="{style.foreground}"/>',
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="{style.foreground}"/>',
        ]
        elements.extend(self._grid_elements(style, left, top, plot_w, plot_h))
        for index, series in enumerate(figure.series):
            values = [float(point.y) for point in series.points]
            q1, q2, q3 = (self._quantile(values, probability) for probability in (0.25, 0.5, 0.75))
            low, high = min(values), max(values)
            center = left + plot_w * (index + 0.5) / len(figure.series)
            box_w = min(80.0, plot_w / max(len(figure.series) * 2, 1))
            color = style.palette[index % len(style.palette)]
            elements.extend((
                f'<line x1="{center:.2f}" y1="{y_pos(low):.2f}" x2="{center:.2f}" y2="{y_pos(high):.2f}" stroke="{color}"/>',
                f'<rect x="{center - box_w / 2:.2f}" y="{y_pos(q3):.2f}" width="{box_w:.2f}" height="{abs(y_pos(q1) - y_pos(q3)):.2f}" fill="{color}" opacity="0.55" stroke="{color}"/>',
                f'<line x1="{center - box_w / 2:.2f}" y1="{y_pos(q2):.2f}" x2="{center + box_w / 2:.2f}" y2="{y_pos(q2):.2f}" stroke="#111"/>',
                f'<text x="{center:.2f}" y="{height - 38}" text-anchor="middle" font-family="sans-serif" font-size="12">{html.escape(series.name)}</text>',
            ))
        elements.append(f'<text x="{width / 2}" y="{height - 18}" text-anchor="middle" font-family="sans-serif" font-size="12">{html.escape(figure.x_label)}</text>')
        elements.append(f'<text x="16" y="{height / 2}" transform="rotate(-90 16 {height / 2})" text-anchor="middle" font-family="sans-serif" font-size="12">{html.escape(figure.y_label)}</text>')
        elements.append("</svg>")
        return "".join(elements)

    def _render_violin(self, figure: FigureSpec) -> str:
        width, height = figure.width, figure.height
        style = figure.style
        background = "none" if style.transparent else style.background
        font = html.escape(style.font_family, quote=True)
        left, top, right, bottom = 72, 48, 28, 64
        plot_w, plot_h = width - left - right, height - top - bottom
        all_values = [float(point.y) for series in figure.series for point in series.points]
        ymin, ymax = min(all_values), max(all_values)
        if math.isclose(ymin, ymax):
            ymax = ymin + 1.0

        def y_pos(value: float) -> float:
            return top + plot_h * (ymax - value) / (ymax - ymin)

        elements = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            f'<rect width="{width}" height="{height}" fill="{background}"/>',
            f'<text x="{width / 2}" y="24" text-anchor="middle" font-family="{font}" font-size="{style.title_size}" font-weight="600" fill="{style.foreground}">{html.escape(figure.title)}</text>',
            f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="{style.foreground}"/>',
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="{style.foreground}"/>',
        ]
        elements.extend(self._grid_elements(style, left, top, plot_w, plot_h))
        for index, series in enumerate(figure.series):
            values = [float(point.y) for point in series.points]
            bandwidth = max((ymax - ymin) / 12.0, 1e-9)
            samples = [ymin + (ymax - ymin) * step / 24.0 for step in range(25)]
            density = [
                sum(math.exp(-0.5 * ((sample - value) / bandwidth) ** 2) for value in values)
                for sample in samples
            ]
            peak = max(density) or 1.0
            center = left + plot_w * (index + 0.5) / max(len(figure.series), 1)
            half_width = min(54.0, plot_w / max(len(figure.series) * 3.0, 1.0))
            upper = [(center + half_width * value / peak, y_pos(sample)) for sample, value in zip(samples, density, strict=True)]
            lower = [(center - half_width * value / peak, y_pos(sample)) for sample, value in zip(reversed(samples), reversed(density), strict=True)]
            path = " ".join((("M" if i == 0 else "L") + f" {x:.2f},{y:.2f}") for i, (x, y) in enumerate(upper + lower)) + " Z"
            color = style.palette[index % len(style.palette)]
            elements.append(f'<path d="{path}" fill="{color}" fill-opacity="0.45" stroke="{color}" stroke-width="{style.line_width}"/>')
            elements.append(f'<text x="{center:.2f}" y="{height - 38}" text-anchor="middle" font-family="{font}" font-size="{style.label_size}" fill="{style.foreground}">{html.escape(series.name)}</text>')
        elements.append(f'<text x="{width / 2}" y="{height - 18}" text-anchor="middle" font-family="{font}" font-size="{style.label_size}" fill="{style.foreground}">{html.escape(figure.x_label)}</text>')
        elements.append(f'<text x="16" y="{height / 2}" transform="rotate(-90 16 {height / 2})" text-anchor="middle" font-family="{font}" font-size="{style.label_size}" fill="{style.foreground}">{html.escape(figure.y_label)}</text>')
        elements.append("</svg>")
        return "".join(elements)

    def _render_ecdf(self, figure: FigureSpec) -> str:
        width, height = figure.width, figure.height
        style = figure.style
        background = "none" if style.transparent else style.background
        font = html.escape(style.font_family, quote=True)
        left, top, right, bottom = 72, 48, 28, 64
        plot_w, plot_h = width - left - right, height - top - bottom
        values = [float(point.y) for series in figure.series for point in series.points]
        xmin, xmax = min(values), max(values)
        if math.isclose(xmin, xmax):
            xmax = xmin + 1.0
        elements = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            f'<rect width="{width}" height="{height}" fill="{background}"/>',
            f'<text x="{width / 2}" y="24" text-anchor="middle" font-family="{font}" font-size="{style.title_size}" font-weight="600" fill="{style.foreground}">{html.escape(figure.title)}</text>',
            f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="{style.foreground}"/>',
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="{style.foreground}"/>',
        ]
        elements.extend(self._grid_elements(style, left, top, plot_w, plot_h))
        for index, series in enumerate(figure.series):
            ordered = sorted(float(point.y) for point in series.points)
            coords = []
            for rank, value in enumerate(ordered, start=1):
                x = left + plot_w * (value - xmin) / (xmax - xmin)
                y = top + plot_h * (1.0 - rank / len(ordered))
                coords.append((x, y))
            color = style.palette[index % len(style.palette)]
            path = " ".join((("M" if i == 0 else "L") + f" {x:.2f},{y:.2f}") for i, (x, y) in enumerate(coords))
            elements.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{style.line_width}"/>')
            elements.append(f'<text x="{left + plot_w - 4}" y="{top + 16 + index * 16}" text-anchor="end" font-family="{font}" font-size="{style.legend_size}" fill="{color}">{html.escape(series.name)}</text>')
        elements.append(f'<text x="{width / 2}" y="{height - 18}" text-anchor="middle" font-family="{font}" font-size="{style.label_size}" fill="{style.foreground}">{html.escape(figure.x_label)}</text>')
        elements.append(f'<text x="16" y="{height / 2}" transform="rotate(-90 16 {height / 2})" text-anchor="middle" font-family="{font}" font-size="{style.label_size}" fill="{style.foreground}">{html.escape(figure.y_label)}</text>')
        elements.append("</svg>")
        return "".join(elements)

    def render(
        self,
        figure: FigureSpec,
        *,
        output_format: FigureOutputFormat = FigureOutputFormat.SVG,
    ) -> str:
        if type(output_format) is not FigureOutputFormat:
            raise TypeError("output_format must be FigureOutputFormat")
        if output_format is not FigureOutputFormat.SVG:
            raise ValueError("SvgFigureRenderer only supports SVG output")
        if figure.kind in {FigureKind.HEATMAP, FigureKind.CONFUSION_MATRIX}:
            return self._render_heatmap(figure)
        if figure.kind is FigureKind.BOXPLOT:
            return self._render_boxplot(figure)
        if figure.kind is FigureKind.VIOLIN:
            return self._render_violin(figure)
        if figure.kind is FigureKind.ECDF:
            return self._render_ecdf(figure)
        width, height = figure.width, figure.height
        style = figure.style
        background = "none" if style.transparent else style.background
        font = html.escape(style.font_family, quote=True)
        left, top, right, bottom = 72, 48, 28, 64
        plot_w, plot_h = width - left - right, height - top - bottom
        points = [point for series in figure.series for point in series.points]
        ys = [float(point.y) for point in points]
        classification_kinds = {FigureKind.ROC, FigureKind.PRECISION_RECALL, FigureKind.CALIBRATION}
        if figure.kind in classification_kinds:
            ymin, ymax = 0.0, max(1.0, max(ys))
        else:
            ymin, ymax = min(0.0, min(ys)), max(0.0, max(ys))
        if math.isclose(ymin, ymax):
            ymax = ymin + 1.0
        numeric_x = all(isinstance(point.x, (int, float)) and not isinstance(point.x, bool) for point in points)
        x_values = [float(point.x) for point in points] if numeric_x else []
        x_min, x_max = (min(x_values), max(x_values)) if x_values else (0.0, 1.0)
        if math.isclose(x_min, x_max):
            x_max = x_min + 1.0
        def x_pos(point: FigurePoint, index: int, point_count: int) -> float:
            if numeric_x:
                return left + plot_w * (float(point.x) - x_min) / (x_max - x_min)
            return left + (plot_w * index / max(point_count - 1, 1))
        def y_pos(value: float) -> float:
            return top + plot_h * (ymax - value) / (ymax - ymin)
        elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
                    f'<rect width="{width}" height="{height}" fill="{background}"/>',
                    f'<text x="{width / 2}" y="24" text-anchor="middle" font-family="{font}" font-size="{style.title_size}" font-weight="600" fill="{style.foreground}">{html.escape(figure.title)}</text>',
                    f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="{style.foreground}"/>',
                    f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="{style.foreground}"/>']
        elements.extend(self._grid_elements(style, left, top, plot_w, plot_h))
        if figure.kind in {FigureKind.ROC, FigureKind.CALIBRATION}:
            elements.append(f'<line x1="{left}" y1="{y_pos(0.0):.2f}" x2="{left + plot_w}" y2="{y_pos(1.0):.2f}" stroke="{style.grid}" stroke-dasharray="6,5" stroke-width="{style.line_width / 2:.2f}"/>')
        colors = style.palette
        for series_index, series in enumerate(figure.series):
            color = colors[series_index % len(colors)]
            coords = [(x_pos(point, i, len(series.points)), y_pos(float(point.y))) for i, point in enumerate(series.points)]
            if figure.kind in {FigureKind.BAR, FigureKind.HISTOGRAM}:
                bar_w = max(8.0, plot_w / max(len(series.points) * len(figure.series), 1) * 0.7)
                for i, (x, y) in enumerate(coords):
                    baseline = y_pos(0.0)
                    elements.append(f'<rect x="{x + series_index * bar_w - bar_w * len(figure.series) / 2:.2f}" y="{min(y, baseline):.2f}" width="{bar_w:.2f}" height="{abs(baseline - y):.2f}" fill="{color}"/>')
            else:
                path = " ".join(("M" if i == 0 else "L") + f" {x:.2f},{y:.2f}" for i, (x, y) in enumerate(coords))
                stroke = "none" if figure.kind is FigureKind.SCATTER else color
                elements.append(f'<path d="{path}" fill="none" stroke="{stroke}" stroke-width="{style.line_width}"/>')
                elements.extend(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{style.marker_size}" fill="{color}"/>' for x, y in coords)
                for point, (x, _) in zip(series.points, coords, strict=True):
                    if point.error_low is not None:
                        low_y, high_y = y_pos(float(point.error_low)), y_pos(float(point.error_high))
                        elements.extend((
                            f'<line x1="{x:.2f}" y1="{low_y:.2f}" x2="{x:.2f}" y2="{high_y:.2f}" stroke="{color}"/>',
                            f'<line x1="{x - 4:.2f}" y1="{low_y:.2f}" x2="{x + 4:.2f}" y2="{low_y:.2f}" stroke="{color}"/>',
                            f'<line x1="{x - 4:.2f}" y1="{high_y:.2f}" x2="{x + 4:.2f}" y2="{high_y:.2f}" stroke="{color}"/>',
                        ))
            elements.append(f'<text x="{left + plot_w - 4}" y="{top + 16 + series_index * 16}" text-anchor="end" font-family="{font}" font-size="{style.legend_size}" fill="{color}">{html.escape(series.name)}</text>')
        elements.append(f'<text x="{width / 2}" y="{height - 18}" text-anchor="middle" font-family="{font}" font-size="{style.label_size}" fill="{style.foreground}">{html.escape(figure.x_label)}</text>')
        elements.append(f'<text x="16" y="{height / 2}" transform="rotate(-90 16 {height / 2})" text-anchor="middle" font-family="{font}" font-size="{style.label_size}" fill="{style.foreground}">{html.escape(figure.y_label)}</text>')
        elements.append("</svg>")
        return "".join(elements)


__all__ = ["CsvTableReader", "JsonlTableReader", "StandardTableRenderer", "SvgFigureRenderer"]