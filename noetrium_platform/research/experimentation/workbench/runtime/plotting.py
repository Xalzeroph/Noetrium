"""High-level publication figure semantics over the shared research table authority.
    
Downstream paper code supplies columns and intent; it does not assemble renderer-specific
objects or duplicate aggregation logic.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from noetrium_platform.foundation.kernel.kernel import canonical_digest, freeze_json
from ..api import (
    DataTable,
    FigureCell,
    FigureKind,
    FigurePoint,
    FigureSeries,
    FigureSpec,
    FigureStyle,
    GroupComparison,
)

def _number(value: object, column: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"figure column {column!r} must contain numeric values")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"figure column {column!r} must contain finite values")
    return result


def _ordered(values: set[object]) -> tuple[object, ...]:
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return tuple(sorted(values, key=float))
    return tuple(sorted(values, key=lambda value: repr(freeze_json(value))))


def _label(value: object) -> str:
    return value if isinstance(value, str) else str(freeze_json(value))


def _point_key(point: FigurePoint) -> tuple[int, object]:
    if isinstance(point.x, (int, float)) and not isinstance(point.x, bool):
        return (0, float(point.x))
    return (1, repr(freeze_json(point.x)))


def _interval(values: list[float]) -> tuple[float, float, float]:
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1) if len(values) > 1 else 0.0
    margin = 1.96 * math.sqrt(variance / len(values))
    return mean, mean - margin, mean + margin


class ResearchFigureFactory:
    """One semantic figure factory for learning curves, benchmarks and paper diagnostics."""

    def __init__(self, *, style: FigureStyle | None = None) -> None:
        self._style = style or FigureStyle.nature()

    @property
    def style(self) -> FigureStyle:
        return self._style

    @staticmethod
    def _id(prefix: str, table: DataTable, *parts: object) -> str:
        digest = canonical_digest((prefix, table.table_digest, parts))
        return f"{prefix}:{digest[:16]}"

    def _figure(
        self,
        table: DataTable,
        *,
        figure_id: str,
        title: str,
        kind: FigureKind,
        series: tuple[FigureSeries, ...] = (),
        cells: tuple[FigureCell, ...] = (),
        x_label: str = "",
        y_label: str = "",
        caption: str = "",
        style: FigureStyle | None = None,
    ) -> FigureSpec:
        return FigureSpec(
            figure_id=figure_id,
            title=title,
            kind=kind,
            series=series,
            x_label=x_label,
            y_label=y_label,
            cells=cells,
            caption=caption,
            source_digests=(table.table_digest,),
            metadata=(("source_table", table.table_id),),
            style=style or self._style,
        )

    def curve(
        self,
        table: DataTable,
        *,
        x_column: str,
        y_column: str,
        series_column: str | None = None,
        title: str = "Learning curve",
        figure_id: str | None = None,
        kind: FigureKind = FigureKind.LINE,
        x_label: str = "",
        y_label: str = "",
        caption: str = "",
        style: FigureStyle | None = None,
    ) -> FigureSpec:
        """Aggregate repeated seeds/episodes into deterministic mean and 95% CI curves."""
        x_index, y_index = table.column_index(x_column), table.column_index(y_column)
        series_index = table.column_index(series_column) if series_column else None
        groups: dict[str, tuple[object, dict[str, list[float]]]] = {}
        for row in table.rows:
            x_value = freeze_json(row[x_index])
            if row[y_index] is None:
                continue
            series_value = freeze_json(row[series_index]) if series_index is not None else "value"
            series_key = _label(series_value)
            key = repr((x_value, series_key))
            if key not in groups:
                groups[key] = (x_value, {series_key: []})
            groups[key][1].setdefault(series_key, []).append(_number(row[y_index], y_column))
        series_values: dict[str, list[FigurePoint]] = defaultdict(list)
        labels: dict[str, str] = {}
        for x_value, by_series in groups.values():
            for series_key, values in by_series.items():
                mean, low, high = _interval(values)
                series_values[series_key].append(FigurePoint(x_value, mean, low, high))
                labels[series_key] = _label(series_key)
        ordered_series = tuple(
            FigureSeries(labels[key], tuple(sorted(points, key=_point_key)))
            for key, points in sorted(series_values.items())
        )
        return self._figure(
            table, figure_id=figure_id or self._id("curve", table, x_column, y_column, series_column),
            title=title, kind=kind, series=ordered_series, x_label=x_label or x_column,
            y_label=y_label or y_column, caption=caption, style=style,
        )

    def benchmark(
        self,
        table: DataTable,
        *,
        method_column: str,
        metric_column: str,
        title: str = "Method comparison",
        figure_id: str | None = None,
        x_label: str = "Method",
        y_label: str = "",
        caption: str = "",
        style: FigureStyle | None = None,
    ) -> FigureSpec:
        """Create a publication comparison bar chart from repetitions or seeds."""
        method_index, metric_index = table.column_index(method_column), table.column_index(metric_column)
        values: dict[str, list[float]] = defaultdict(list)
        for row in table.rows:
            if row[metric_index] is not None:
                values[_label(row[method_index])].append(_number(row[metric_index], metric_column))
        series = tuple(
            FigureSeries(method, (FigurePoint(method, *_interval(samples)),))
            for method, samples in sorted(values.items())
        )
        return self._figure(
            table, figure_id=figure_id or self._id("benchmark", table, method_column, metric_column),
            title=title, kind=FigureKind.BAR, series=series, x_label=x_label,
            y_label=y_label or metric_column, caption=caption, style=style,
        )

    def distribution(
        self,
        table: DataTable,
        *,
        value_column: str,
        group_column: str,
        title: str = "Distribution",
        figure_id: str | None = None,
        kind: FigureKind = FigureKind.BOXPLOT,
        x_label: str = "",
        y_label: str = "",
        caption: str = "",
        style: FigureStyle | None = None,
    ) -> FigureSpec:
        """Create a boxplot or violin-ready distribution figure without reshaping downstream data."""
        value_index, group_index = table.column_index(value_column), table.column_index(group_column)
        values: dict[str, list[float]] = defaultdict(list)
        for row in table.rows:
            if row[value_index] is not None:
                values[_label(row[group_index])].append(_number(row[value_index], value_column))
        series = tuple(
            FigureSeries(group, tuple(FigurePoint(group, value) for value in samples))
            for group, samples in sorted(values.items())
        )
        return self._figure(
            table, figure_id=figure_id or self._id("distribution", table, value_column, group_column),
            title=title, kind=kind, series=series, x_label=x_label or group_column,
            y_label=y_label or value_column, caption=caption, style=style,
        )

    def matrix(
        self,
        table: DataTable,
        *,
        row_column: str,
        column_column: str,
        value_column: str,
        title: str = "Matrix",
        figure_id: str | None = None,
        kind: FigureKind = FigureKind.HEATMAP,
        x_label: str = "",
        y_label: str = "",
        caption: str = "",
        style: FigureStyle | None = None,
    ) -> FigureSpec:
        row_index = table.column_index(row_column)
        column_index = table.column_index(column_column)
        value_index = table.column_index(value_column)
        cells = tuple(
            FigureCell(row=freeze_json(row[row_index]), column=freeze_json(row[column_index]),
                       value=_number(row[value_index], value_column))
            for row in table.rows if row[value_index] is not None
        )
        return self._figure(
            table, figure_id=figure_id or self._id("matrix", table, row_column, column_column, value_column),
            title=title, kind=kind, cells=cells, x_label=x_label or column_column,
            y_label=y_label or row_column, caption=caption, style=style,
        )

    def classification_curve(
        self,
        table: DataTable,
        *,
        x_column: str,
        y_column: str,
        kind: FigureKind,
        series_column: str | None = None,
        title: str | None = None,
        figure_id: str | None = None,
        x_label: str = "",
        y_label: str = "",
        caption: str = "",
        style: FigureStyle | None = None,
    ) -> FigureSpec:
        """Build ROC, precision-recall, or calibration curves through the same curve authority."""
        if kind not in {FigureKind.ROC, FigureKind.PRECISION_RECALL, FigureKind.CALIBRATION}:
            raise ValueError("classification_curve kind must be ROC, PRECISION_RECALL, or CALIBRATION")
        defaults = {
            FigureKind.ROC: ("ROC curve", "False-positive rate", "True-positive rate"),
            FigureKind.PRECISION_RECALL: ("Precision-recall curve", "Recall", "Precision"),
            FigureKind.CALIBRATION: ("Calibration curve", "Predicted probability", "Observed frequency"),
        }
        default_title, default_x, default_y = defaults[kind]
        return self.curve(
            table,
            x_column=x_column,
            y_column=y_column,
            series_column=series_column,
            title=title or default_title,
            figure_id=figure_id,
            kind=kind,
            x_label=x_label or default_x,
            y_label=y_label or default_y,
            caption=caption,
            style=style,
        )

    def pareto(
        self,
        table: DataTable,
        *,
        x_column: str,
        y_column: str,
        label_column: str | None = None,
        title: str = "Pareto frontier",
        figure_id: str | None = None,
        x_label: str = "",
        y_label: str = "",
        caption: str = "",
        style: FigureStyle | None = None,
    ) -> FigureSpec:
        x_index, y_index = table.column_index(x_column), table.column_index(y_column)
        label_index = table.column_index(label_column) if label_column else None
        points = tuple(
            FigurePoint(_label(row[label_index]) if label_index is not None else _number(row[x_index], x_column),
                        _number(row[y_index], y_column))
            for row in table.rows
        )
        return self._figure(
            table, figure_id=figure_id or self._id("pareto", table, x_column, y_column, label_column),
            title=title, kind=FigureKind.PARETO, series=(FigureSeries(label_column or x_column, points),),
            x_label=x_label or x_column, y_label=y_label or y_column, caption=caption, style=style,
        )

    def effects(
        self,
        comparisons: tuple[GroupComparison, ...],
        *,
        title: str = "Estimated effects",
        figure_id: str = "effects",
        x_label: str = "Candidate",
        y_label: str = "Difference",
        caption: str = "",
        style: FigureStyle | None = None,
    ) -> FigureSpec:
        """Render baseline comparisons as a forest-style uncertainty figure."""
        if type(comparisons) is not tuple or not comparisons:
            raise ValueError("effects requires a non-empty tuple of GroupComparison")
        series = tuple(
            FigureSeries(
                _label(comparison.candidate),
                (FigurePoint(
                    _label(comparison.candidate),
                    comparison.difference,
                    comparison.confidence95_low,
                    comparison.confidence95_high,
                ),),
            )
            for comparison in comparisons
        )
        return FigureSpec(
            figure_id=figure_id,
            title=title,
            kind=FigureKind.FOREST,
            series=series,
            x_label=x_label,
            y_label=y_label,
            caption=caption,
            source_digests=tuple(canonical_digest(comparison) for comparison in comparisons),
            metadata=(("metric", comparisons[0].metric), ("group_column", comparisons[0].group_column)),
            style=style or self._style,
        )


__all__ = ["ResearchFigureFactory"]
