from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import endpoint_unit, relation_unit, structure_unit

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest, freeze_json
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, NoetriumUnit, NoetriumUnit

from .contracts import AggregationFunction, DataColumn, DataTable, MissingValuePolicy
from .unit_semantics import (
    aggregation_data_type,
    aggregation_function,
    aggregation_output_name,
    aggregation_source_column,
    require_aggregation,
)


class TableExpressionKind(StrEnum):
    COLUMN = "column"
    LITERAL = "literal"
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    LESS_THAN = "less_than"
    LESS_EQUAL = "less_equal"
    GREATER_THAN = "greater_than"
    GREATER_EQUAL = "greater_equal"
    AND = "and"
    OR = "or"
    NOT = "not"
    IS_NULL = "is_null"
    COALESCE = "coalesce"


_BINARY_KINDS = frozenset(
    {
        TableExpressionKind.ADD,
        TableExpressionKind.SUBTRACT,
        TableExpressionKind.MULTIPLY,
        TableExpressionKind.DIVIDE,
        TableExpressionKind.EQUAL,
        TableExpressionKind.NOT_EQUAL,
        TableExpressionKind.LESS_THAN,
        TableExpressionKind.LESS_EQUAL,
        TableExpressionKind.GREATER_THAN,
        TableExpressionKind.GREATER_EQUAL,
        TableExpressionKind.AND,
        TableExpressionKind.OR,
        TableExpressionKind.COALESCE,
    }
)
_UNARY_KINDS = frozenset({TableExpressionKind.NOT, TableExpressionKind.IS_NULL})


@dataclass(frozen=True, slots=True)
class TableExpression:
    """Portable immutable table expression with stable semantic identity."""

    kind: TableExpressionKind
    operands: tuple["TableExpression", ...] = ()
    column_name: str | None = None
    literal_value: JsonValue = None
    expression_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TableExpressionKind):
            raise TypeError("table expression kind must be TableExpressionKind")
        if type(self.operands) is not tuple or any(
            type(item) is not TableExpression for item in self.operands
        ):
            raise TypeError("table expression operands must contain TableExpression")
        if self.kind is TableExpressionKind.COLUMN:
            if type(self.column_name) is not str or not self.column_name.strip():
                raise ValueError("column expression requires a non-empty column_name")
            if self.operands:
                raise ValueError("column expression cannot have operands")
        elif self.kind is TableExpressionKind.LITERAL:
            if self.column_name is not None or self.operands:
                raise ValueError("literal expression cannot have column_name or operands")
            object.__setattr__(self, "literal_value", freeze_json(self.literal_value))
        elif self.kind in _UNARY_KINDS:
            if self.column_name is not None or len(self.operands) != 1:
                raise ValueError(f"{self.kind.value} expression requires one operand")
        elif self.kind in _BINARY_KINDS:
            if self.column_name is not None or len(self.operands) != 2:
                raise ValueError(f"{self.kind.value} expression requires two operands")
        else:
            raise ValueError(f"unsupported table expression kind: {self.kind}")
        object.__setattr__(self, "expression_digest", canonical_digest(self.document()))

    @classmethod
    def column(cls, name: str) -> "TableExpression":
        return cls(TableExpressionKind.COLUMN, column_name=name)

    @classmethod
    def literal(cls, value: JsonValue) -> "TableExpression":
        return cls(TableExpressionKind.LITERAL, literal_value=value)

    @classmethod
    def unary(
        cls,
        kind: TableExpressionKind,
        operand: "TableExpression",
    ) -> "TableExpression":
        return cls(kind, (operand,))

    @classmethod
    def binary(
        cls,
        kind: TableExpressionKind,
        left: "TableExpression",
        right: "TableExpression",
    ) -> "TableExpression":
        return cls(kind, (left, right))

    def document(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind.value,
            "operands": tuple(item.document() for item in self.operands),
            "column_name": self.column_name,
            "literal_value": self.literal_value,
        }


TABLE_PROGRAM_TRAIT = "table.program"
TABLE_STEP_TRAIT = "table.step"


def _column_document(column: DataColumn) -> dict[str, JsonValue]:
    return {"name": column.name, "data_type": column.data_type, "nullable": column.nullable}


def _aggregation_document(item: NoetriumUnit) -> dict[str, JsonValue]:
    item=require_aggregation(item)
    return {
        "output_name": aggregation_output_name(item),
        "function": aggregation_function(item).value,
        "source_column": aggregation_source_column(item),
        "data_type": aggregation_data_type(item),
    }


def table_step_graph(kind: str, *, index: int, parameters: dict[str, JsonValue]) -> NoetriumUnit:
    if kind not in {"project", "filter", "derive", "aggregate", "join"}:
        raise ValueError(f"unsupported table step kind: {kind}")
    if type(index) is not int or index < 0:
        raise ValueError("table step index must be non-negative")
    return structure_unit(f"step:{index}", traits=(TABLE_STEP_TRAIT, f"table.step.{kind}"), parameters={"kind": kind, **parameters})


def table_project_step(columns: tuple[str, ...], *, index: int) -> NoetriumUnit:
    if type(columns) is not tuple or not columns or len(columns) != len(set(columns)) or any(type(x) is not str or not x.strip() for x in columns):
        raise ValueError("table project columns must be unique non-empty strings")
    return table_step_graph("project", index=index, parameters={"columns": columns})


def table_filter_step(predicate: TableExpression, *, index: int) -> NoetriumUnit:
    if type(predicate) is not TableExpression: raise TypeError("table filter predicate must be TableExpression")
    return table_step_graph("filter", index=index, parameters={"predicate": predicate.document()})


def table_derive_step(column: DataColumn, expression: TableExpression, *, index: int) -> NoetriumUnit:
    if type(column) is not DataColumn or type(expression) is not TableExpression: raise TypeError("table derive requires DataColumn and TableExpression")
    return table_step_graph("derive", index=index, parameters={"column": _column_document(column), "expression": expression.document()})


def table_aggregate_step(group_by: tuple[str, ...], aggregations: tuple[NoetriumUnit, ...], *, index: int, missing: MissingValuePolicy = MissingValuePolicy.SKIP) -> NoetriumUnit:
    if type(group_by) is not tuple or len(group_by) != len(set(group_by)): raise ValueError("table aggregate group_by must be unique tuple")
    if type(aggregations) is not tuple or not aggregations or any(type(x) is not NoetriumUnit for x in aggregations): raise ValueError("table aggregate requires aggregations")
    if not isinstance(missing, MissingValuePolicy): raise TypeError("table aggregate missing must be MissingValuePolicy")
    return table_step_graph("aggregate", index=index, parameters={"group_by": group_by, "aggregations": tuple(_aggregation_document(x) for x in aggregations), "missing": missing.value})


def table_join_step(right_input: str, on: tuple[str, ...], *, index: int, how: str = "inner") -> NoetriumUnit:
    if type(right_input) is not str or not right_input.strip(): raise ValueError("table join right_input must be non-empty")
    if type(on) is not tuple or not on or len(on) != len(set(on)): raise ValueError("table join keys must be unique non-empty tuple")
    if how not in {"inner", "left"}: raise ValueError("table join how must be inner or left")
    return table_step_graph("join", index=index, parameters={"right_input": right_input, "on": on, "how": how})


def table_program_graph(program_id: str, primary_input: str, steps: tuple[NoetriumUnit, ...]) -> NoetriumUnit:
    if type(program_id) is not str or not program_id.strip(): raise ValueError("table program_id must be non-empty")
    if type(primary_input) is not str or not primary_input.strip(): raise ValueError("table primary_input must be non-empty")
    if type(steps) is not tuple or not steps: raise ValueError("table program requires steps")
    if any(type(x) is not NoetriumUnit or not x.has_trait(TABLE_STEP_TRAIT) for x in steps): raise TypeError("table program steps must be table-step NoetriumUnit")
    expected=tuple(f"step:{i}" for i in range(len(steps)))
    if tuple(x.unit_id for x in steps) != expected: raise ValueError("table program steps must use canonical contiguous indices")
    relations=tuple(relation_unit((endpoint_unit(steps[i].unit_id, None),),(endpoint_unit(steps[i+1].unit_id, None),),"table.flow") for i in range(len(steps)-1))
    return structure_unit(f"table:{canonical_digest((program_id, primary_input))[:24]}", traits=(TABLE_PROGRAM_TRAIT,), parameters={"program_id": program_id, "primary_input": primary_input}, members=steps, relations=relations)


def require_table_program(graph: NoetriumUnit) -> NoetriumUnit:
    if type(graph) is not NoetriumUnit or not graph.has_trait(TABLE_PROGRAM_TRAIT): raise TypeError("table program must be NoetriumUnit")
    return graph

@dataclass(frozen=True, slots=True)
class TableExecutionReceipt:
    program_digest: str
    input_digests: tuple[tuple[str, str], ...]
    output_digest: str
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("program_digest", self.program_digest),
            ("output_digest", self.output_digest),
        ):
            if type(value) is not str or len(value) != 64 or any(
                char not in "0123456789abcdef" for char in value
            ):
                raise ValueError(f"table execution {name} must be lowercase SHA-256")
        if type(self.input_digests) is not tuple or not self.input_digests:
            raise ValueError("table execution input_digests must be non-empty")
        names = []
        for item in self.input_digests:
            if type(item) is not tuple or len(item) != 2:
                raise TypeError("table execution input digest rows must be pairs")
            name, digest = item
            if type(name) is not str or not name.strip():
                raise ValueError("table execution input name must be non-empty")
            if type(digest) is not str or len(digest) != 64 or any(
                char not in "0123456789abcdef" for char in digest
            ):
                raise ValueError("table execution input digest must be lowercase SHA-256")
            names.append(name)
        if len(names) != len(set(names)):
            raise ValueError("table execution input names must be unique")
        object.__setattr__(
            self,
            "receipt_digest",
            canonical_digest(
                {
                    "program_digest": self.program_digest,
                    "input_digests": self.input_digests,
                    "output_digest": self.output_digest,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class TableExecutionResult:
    table: DataTable
    receipt: TableExecutionReceipt

    def __post_init__(self) -> None:
        if type(self.table) is not DataTable:
            raise TypeError("table execution result table must be DataTable")
        if type(self.receipt) is not TableExecutionReceipt:
            raise TypeError("table execution result receipt must be TableExecutionReceipt")
        if self.receipt.output_digest != self.table.table_digest:
            raise ValueError("table execution receipt output digest mismatch")


class TableProgramExecutionPort(Protocol):
    def execute(
        self,
        program: NoetriumUnit,
        inputs: tuple[tuple[str, DataTable], ...],
    ) -> TableExecutionResult: ...


__all__ = [
    "TABLE_PROGRAM_TRAIT", "TABLE_STEP_TRAIT",
    "TableExecutionReceipt", "TableExecutionResult", "TableExpression", "TableExpressionKind",
    "TableProgramExecutionPort", "table_step_graph", "table_project_step", "table_filter_step",
    "table_derive_step", "table_aggregate_step", "table_join_step", "table_program_graph", "require_table_program",
]
