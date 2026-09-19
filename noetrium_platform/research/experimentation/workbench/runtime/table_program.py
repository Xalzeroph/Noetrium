from __future__ import annotations

from collections import defaultdict
import math
from statistics import median
from typing import Any

from noetrium_platform.foundation.kernel.kernel import JsonValue, freeze_json

from ..api.contracts import (
    AggregationFunction,
    AggregationSpec,
    DataColumn,
    DataTable,
    MissingValuePolicy,
)
from ..api.table_program import (
    TableAggregateStep,
    TableDeriveStep,
    TableExecutionReceipt,
    TableExecutionResult,
    TableExpression,
    TableExpressionKind,
    TableFilterStep,
    TableJoinStep,
    TableProgram,
    TableProjectStep,
)


def _numeric(value: JsonValue, *, expression: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{expression} requires numeric operands")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{expression} requires finite numeric operands")
    return numeric


def _boolean(value: JsonValue, *, expression: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{expression} requires boolean operands")
    return value


def _evaluate(expression: TableExpression, row: dict[str, JsonValue]) -> JsonValue:
    kind = expression.kind
    if kind is TableExpressionKind.COLUMN:
        assert expression.column_name is not None
        try:
            return row[expression.column_name]
        except KeyError as exc:
            raise KeyError(
                f"table expression references missing column {expression.column_name!r}"
            ) from exc
    if kind is TableExpressionKind.LITERAL:
        return expression.literal_value

    values = tuple(_evaluate(item, row) for item in expression.operands)

    if kind is TableExpressionKind.NOT:
        return not _boolean(values[0], expression=kind.value)
    if kind is TableExpressionKind.IS_NULL:
        return values[0] is None
    if kind is TableExpressionKind.COALESCE:
        return values[0] if values[0] is not None else values[1]
    if kind is TableExpressionKind.AND:
        return _boolean(values[0], expression=kind.value) and _boolean(
            values[1], expression=kind.value
        )
    if kind is TableExpressionKind.OR:
        return _boolean(values[0], expression=kind.value) or _boolean(
            values[1], expression=kind.value
        )
    if kind is TableExpressionKind.EQUAL:
        return values[0] == values[1]
    if kind is TableExpressionKind.NOT_EQUAL:
        return values[0] != values[1]

    if kind in {
        TableExpressionKind.LESS_THAN,
        TableExpressionKind.LESS_EQUAL,
        TableExpressionKind.GREATER_THAN,
        TableExpressionKind.GREATER_EQUAL,
    }:
        if values[0] is None or values[1] is None:
            raise TypeError(f"{kind.value} does not accept null operands")
        try:
            if kind is TableExpressionKind.LESS_THAN:
                return values[0] < values[1]
            if kind is TableExpressionKind.LESS_EQUAL:
                return values[0] <= values[1]
            if kind is TableExpressionKind.GREATER_THAN:
                return values[0] > values[1]
            return values[0] >= values[1]
        except TypeError as exc:
            raise TypeError(f"{kind.value} operands are not comparable") from exc

    left = _numeric(values[0], expression=kind.value)
    right = _numeric(values[1], expression=kind.value)
    if kind is TableExpressionKind.ADD:
        result = left + right
    elif kind is TableExpressionKind.SUBTRACT:
        result = left - right
    elif kind is TableExpressionKind.MULTIPLY:
        result = left * right
    elif kind is TableExpressionKind.DIVIDE:
        if right == 0.0:
            raise ZeroDivisionError("table expression division by zero")
        result = left / right
    else:
        raise ValueError(f"unsupported table expression kind: {kind}")
    if not math.isfinite(result):
        raise ValueError(f"{kind.value} produced a non-finite numeric value")
    return result


def _derived_table(
    table: DataTable,
    *,
    operation_id: str,
    configuration_digest: str,
    columns: tuple[DataColumn, ...],
    rows: tuple[tuple[JsonValue, ...], ...],
    additional_lineage: tuple[str, ...] = (),
) -> DataTable:
    metadata = tuple(
        item for item in table.metadata if item[0] != "last_operation"
    ) + (("last_operation", operation_id),)
    return DataTable(
        table.table_id,
        columns,
        rows,
        source_digest=table.source_digest,
        lineage_digests=tuple(
            dict.fromkeys(
                table.lineage_digests
                + (table.table_digest, configuration_digest)
                + additional_lineage
            )
        ),
        metadata=metadata,
    )


def _group_key(
    row: tuple[JsonValue, ...],
    indexes: tuple[int, ...],
) -> tuple[str, ...]:
    return tuple(repr(freeze_json(row[index])) for index in indexes)


def _group_rows(
    rows: tuple[tuple[JsonValue, ...], ...],
    indexes: tuple[int, ...],
) -> tuple[tuple[tuple[str, ...], tuple[tuple[JsonValue, ...], ...]], ...]:
    groups: dict[tuple[str, ...], list[tuple[JsonValue, ...]]] = defaultdict(list)
    for row in rows:
        groups[_group_key(row, indexes)].append(row)
    return tuple(
        (key, tuple(group))
        for key, group in sorted(groups.items(), key=lambda item: item[0])
    )


def _aggregate_value(
    rows: tuple[tuple[JsonValue, ...], ...],
    spec: AggregationSpec,
    source_index: int | None,
    missing: MissingValuePolicy,
) -> JsonValue:
    if spec.function is AggregationFunction.COUNT:
        return len(rows)

    assert source_index is not None
    numeric: list[float] = []
    for row in rows:
        value = row[source_index]
        if value is None:
            if missing is MissingValuePolicy.SKIP:
                continue
            raise ValueError(
                f"aggregate column {spec.source_column!r} contains a missing value"
            )
        numeric.append(
            _numeric(value, expression=f"aggregate:{spec.source_column}")
        )

    if not numeric:
        if missing is MissingValuePolicy.REJECT:
            raise ValueError(
                f"aggregate column {spec.source_column!r} has no usable values"
            )
        return None

    mean_value = sum(numeric) / len(numeric)
    if spec.function is AggregationFunction.SUM:
        return sum(numeric)
    if spec.function is AggregationFunction.MEAN:
        return mean_value
    if spec.function is AggregationFunction.VARIANCE:
        return (
            sum((value - mean_value) ** 2 for value in numeric) / (len(numeric) - 1)
            if len(numeric) > 1
            else 0.0
        )
    if spec.function is AggregationFunction.STANDARD_DEVIATION:
        return (
            math.sqrt(
                sum((value - mean_value) ** 2 for value in numeric)
                / (len(numeric) - 1)
            )
            if len(numeric) > 1
            else 0.0
        )
    if spec.function is AggregationFunction.MINIMUM:
        return min(numeric)
    if spec.function is AggregationFunction.MEDIAN:
        return median(numeric)
    if spec.function is AggregationFunction.MAXIMUM:
        return max(numeric)
    raise ValueError(f"unsupported aggregation function: {spec.function}")


class TableProgramExecutor:
    """Execute immutable table semantics without owning source-data authority."""

    def execute(
        self,
        program: TableProgram,
        inputs: tuple[tuple[str, DataTable], ...],
    ) -> TableExecutionResult:
        if type(program) is not TableProgram:
            raise TypeError("table executor requires TableProgram")
        if type(inputs) is not tuple or not inputs:
            raise ValueError("table executor requires input tables")

        tables: dict[str, DataTable] = {}
        for item in inputs:
            if type(item) is not tuple or len(item) != 2:
                raise TypeError("table executor inputs must be name/table pairs")
            name, table = item
            if type(name) is not str or not name.strip():
                raise ValueError("table executor input name must be non-empty")
            if type(table) is not DataTable:
                raise TypeError("table executor input values must be DataTable")
            if name in tables:
                raise ValueError(f"duplicate table executor input {name!r}")
            tables[name] = table

        try:
            current = tables[program.primary_input]
        except KeyError as exc:
            raise KeyError(
                f"table program primary input {program.primary_input!r} is missing"
            ) from exc

        for index, step in enumerate(program.steps):
            operation_id = f"{program.program_id}:{index}:{step.kind.value}"
            if type(step) is TableProjectStep:
                current = self._project(
                    current,
                    step,
                    operation_id=operation_id,
                )
            elif type(step) is TableFilterStep:
                current = self._filter(
                    current,
                    step,
                    operation_id=operation_id,
                )
            elif type(step) is TableDeriveStep:
                current = self._derive(
                    current,
                    step,
                    operation_id=operation_id,
                )
            elif type(step) is TableAggregateStep:
                current = self._aggregate(
                    current,
                    step,
                    operation_id=operation_id,
                )
            elif type(step) is TableJoinStep:
                try:
                    right = tables[step.right_input]
                except KeyError as exc:
                    raise KeyError(
                        f"table join input {step.right_input!r} is missing"
                    ) from exc
                current = self._join(
                    current,
                    right,
                    step,
                    operation_id=operation_id,
                )
            else:
                raise TypeError(f"unsupported table program step {type(step)!r}")

        metadata = tuple(
            item
            for item in current.metadata
            if item[0] != "table_program_digest"
        ) + (("table_program_digest", program.program_digest),)
        current = DataTable(
            current.table_id,
            current.columns,
            current.rows,
            source_digest=current.source_digest,
            lineage_digests=tuple(
                dict.fromkeys(current.lineage_digests + (program.program_digest,))
            ),
            metadata=metadata,
        )
        input_digests = tuple(
            sorted((name, table.table_digest) for name, table in tables.items())
        )
        receipt = TableExecutionReceipt(
            program_digest=program.program_digest,
            input_digests=input_digests,
            output_digest=current.table_digest,
        )
        return TableExecutionResult(current, receipt)

    @staticmethod
    def _project(
        table: DataTable,
        step: TableProjectStep,
        *,
        operation_id: str,
    ) -> DataTable:
        indexes = tuple(table.column_index(name) for name in step.columns)
        columns = tuple(table.columns[index] for index in indexes)
        rows = tuple(
            tuple(row[index] for index in indexes)
            for row in table.rows
        )
        return _derived_table(
            table,
            operation_id=operation_id,
            configuration_digest=step.step_digest,
            columns=columns,
            rows=rows,
        )

    @staticmethod
    def _filter(
        table: DataTable,
        step: TableFilterStep,
        *,
        operation_id: str,
    ) -> DataTable:
        names = table.column_names
        rows = []
        for source_row in table.rows:
            row = dict(zip(names, source_row, strict=True))
            keep = _evaluate(step.predicate, row)
            if type(keep) is not bool:
                raise TypeError("table filter predicate must evaluate to boolean")
            if keep:
                rows.append(source_row)
        return _derived_table(
            table,
            operation_id=operation_id,
            configuration_digest=step.step_digest,
            columns=table.columns,
            rows=tuple(rows),
        )

    @staticmethod
    def _derive(
        table: DataTable,
        step: TableDeriveStep,
        *,
        operation_id: str,
    ) -> DataTable:
        if step.column.name in table.column_names:
            raise ValueError(f"derived column already exists: {step.column.name}")
        names = table.column_names
        rows = tuple(
            row
            + (
                freeze_json(
                    _evaluate(
                        step.expression,
                        dict(zip(names, row, strict=True)),
                    )
                ),
            )
            for row in table.rows
        )
        return _derived_table(
            table,
            operation_id=operation_id,
            configuration_digest=step.step_digest,
            columns=table.columns + (step.column,),
            rows=rows,
        )

    @staticmethod
    def _aggregate(
        table: DataTable,
        step: TableAggregateStep,
        *,
        operation_id: str,
    ) -> DataTable:
        group_indexes = tuple(table.column_index(name) for name in step.group_by)
        source_indexes = tuple(
            None
            if spec.source_column is None
            else table.column_index(spec.source_column)
            for spec in step.aggregations
        )
        columns = tuple(table.columns[index] for index in group_indexes)
        output_columns = tuple(
            DataColumn(spec.output_name, spec.data_type, step.missing is MissingValuePolicy.SKIP)
            for spec in step.aggregations
        )
        output_rows: list[tuple[JsonValue, ...]] = []
        for _, rows in _group_rows(table.rows, group_indexes):
            group_values = tuple(rows[0][index] for index in group_indexes)
            aggregate_values = tuple(
                _aggregate_value(rows, spec, source_index, step.missing)
                for spec, source_index in zip(
                    step.aggregations,
                    source_indexes,
                    strict=True,
                )
            )
            output_rows.append(group_values + aggregate_values)
        return _derived_table(
            table,
            operation_id=operation_id,
            configuration_digest=step.step_digest,
            columns=columns + output_columns,
            rows=tuple(output_rows),
        )

    @staticmethod
    def _join(
        left: DataTable,
        right: DataTable,
        step: TableJoinStep,
        *,
        operation_id: str,
    ) -> DataTable:
        left_indexes = tuple(left.column_index(name) for name in step.on)
        right_indexes = tuple(right.column_index(name) for name in step.on)
        right_only = tuple(
            (index, column)
            for index, column in enumerate(right.columns)
            if column.name not in step.on
        )
        if any(column.name in left.column_names for _, column in right_only):
            raise ValueError("table join output columns must be unique")

        right_index: dict[
            tuple[str, ...],
            list[tuple[JsonValue, ...]],
        ] = defaultdict(list)
        for row in right.rows:
            right_index[_group_key(row, right_indexes)].append(row)

        rows: list[tuple[JsonValue, ...]] = []
        for left_row in left.rows:
            matches = right_index.get(_group_key(left_row, left_indexes), ())
            if matches:
                for right_row in matches:
                    rows.append(
                        left_row
                        + tuple(right_row[index] for index, _ in right_only)
                    )
            elif step.how == "left":
                rows.append(left_row + tuple(None for _ in right_only))

        return _derived_table(
            left,
            operation_id=operation_id,
            configuration_digest=step.step_digest,
            columns=left.columns + tuple(column for _, column in right_only),
            rows=tuple(rows),
            additional_lineage=(right.table_digest,),
        )


__all__ = ["TableProgramExecutor"]
