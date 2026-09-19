from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest, freeze_json

from .contracts import AggregationSpec, DataColumn, DataTable, MissingValuePolicy


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


class TableStepKind(StrEnum):
    PROJECT = "project"
    FILTER = "filter"
    DERIVE = "derive"
    AGGREGATE = "aggregate"
    JOIN = "join"


@dataclass(frozen=True, slots=True)
class TableProjectStep:
    columns: tuple[str, ...]
    kind: TableStepKind = field(default=TableStepKind.PROJECT, init=False)
    step_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.columns) is not tuple or not self.columns:
            raise ValueError("table project columns must be a non-empty tuple")
        if any(type(name) is not str or not name.strip() for name in self.columns):
            raise ValueError("table project columns must be non-empty strings")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("table project columns must be unique")
        object.__setattr__(self, "step_digest", canonical_digest(self.document()))

    def document(self) -> dict[str, JsonValue]:
        return {"kind": self.kind.value, "columns": self.columns}


@dataclass(frozen=True, slots=True)
class TableFilterStep:
    predicate: TableExpression
    kind: TableStepKind = field(default=TableStepKind.FILTER, init=False)
    step_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.predicate) is not TableExpression:
            raise TypeError("table filter predicate must be TableExpression")
        object.__setattr__(self, "step_digest", canonical_digest(self.document()))

    def document(self) -> dict[str, JsonValue]:
        return {"kind": self.kind.value, "predicate": self.predicate.document()}


@dataclass(frozen=True, slots=True)
class TableDeriveStep:
    column: DataColumn
    expression: TableExpression
    kind: TableStepKind = field(default=TableStepKind.DERIVE, init=False)
    step_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.column) is not DataColumn:
            raise TypeError("table derive column must be DataColumn")
        if type(self.expression) is not TableExpression:
            raise TypeError("table derive expression must be TableExpression")
        object.__setattr__(self, "step_digest", canonical_digest(self.document()))

    def document(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind.value,
            "column": {
                "name": self.column.name,
                "data_type": self.column.data_type,
                "nullable": self.column.nullable,
            },
            "expression": self.expression.document(),
        }


@dataclass(frozen=True, slots=True)
class TableAggregateStep:
    group_by: tuple[str, ...]
    aggregations: tuple[AggregationSpec, ...]
    missing: MissingValuePolicy = MissingValuePolicy.SKIP
    kind: TableStepKind = field(default=TableStepKind.AGGREGATE, init=False)
    step_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.group_by) is not tuple:
            raise TypeError("table aggregate group_by must be a tuple")
        if any(type(name) is not str or not name.strip() for name in self.group_by):
            raise ValueError("table aggregate group_by must contain non-empty strings")
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("table aggregate group_by must be unique")
        if type(self.aggregations) is not tuple or not self.aggregations:
            raise ValueError("table aggregate aggregations must be non-empty")
        if any(type(item) is not AggregationSpec for item in self.aggregations):
            raise TypeError("table aggregate aggregations must contain AggregationSpec")
        if not isinstance(self.missing, MissingValuePolicy):
            raise TypeError("table aggregate missing must be MissingValuePolicy")
        object.__setattr__(self, "step_digest", canonical_digest(self.document()))

    def document(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind.value,
            "group_by": self.group_by,
            "aggregations": tuple(
                {
                    "output_name": item.output_name,
                    "function": item.function.value,
                    "source_column": item.source_column,
                    "data_type": item.data_type,
                }
                for item in self.aggregations
            ),
            "missing": self.missing.value,
        }


@dataclass(frozen=True, slots=True)
class TableJoinStep:
    right_input: str
    on: tuple[str, ...]
    how: str = "inner"
    kind: TableStepKind = field(default=TableStepKind.JOIN, init=False)
    step_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.right_input) is not str or not self.right_input.strip():
            raise ValueError("table join right_input must be non-empty")
        if type(self.on) is not tuple or not self.on:
            raise ValueError("table join keys must be a non-empty tuple")
        if any(type(name) is not str or not name.strip() for name in self.on):
            raise ValueError("table join keys must be non-empty strings")
        if len(set(self.on)) != len(self.on):
            raise ValueError("table join keys must be unique")
        if self.how not in {"inner", "left"}:
            raise ValueError("table join how must be inner or left")
        object.__setattr__(self, "step_digest", canonical_digest(self.document()))

    def document(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind.value,
            "right_input": self.right_input,
            "on": self.on,
            "how": self.how,
        }


TableProgramStep = (
    TableProjectStep
    | TableFilterStep
    | TableDeriveStep
    | TableAggregateStep
    | TableJoinStep
)


@dataclass(frozen=True, slots=True)
class TableProgram:
    """Immutable, replayable table transformation program."""

    program_id: str
    primary_input: str
    steps: tuple[TableProgramStep, ...]
    program_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.program_id) is not str or not self.program_id.strip():
            raise ValueError("table program_id must be non-empty")
        if type(self.primary_input) is not str or not self.primary_input.strip():
            raise ValueError("table program primary_input must be non-empty")
        if type(self.steps) is not tuple or not self.steps:
            raise ValueError("table program requires at least one step")
        allowed = (
            TableProjectStep,
            TableFilterStep,
            TableDeriveStep,
            TableAggregateStep,
            TableJoinStep,
        )
        if any(type(step) not in allowed for step in self.steps):
            raise TypeError("table program contains an unsupported step")
        object.__setattr__(
            self,
            "program_digest",
            canonical_digest(
                {
                    "schema": "noetrium.table-program.v1",
                    "program_id": self.program_id,
                    "primary_input": self.primary_input,
                    "steps": tuple(step.document() for step in self.steps),
                }
            ),
        )


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
        program: TableProgram,
        inputs: tuple[tuple[str, DataTable], ...],
    ) -> TableExecutionResult: ...


__all__ = [
    "TableAggregateStep",
    "TableDeriveStep",
    "TableExecutionReceipt",
    "TableExecutionResult",
    "TableExpression",
    "TableExpressionKind",
    "TableFilterStep",
    "TableJoinStep",
    "TableProgram",
    "TableProgramExecutionPort",
    "TableProgramStep",
    "TableProjectStep",
    "TableStepKind",
]
