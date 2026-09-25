"""Typed, explicitly authorized local tool capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock
from typing import Callable, Protocol

from noetrium.contracts.json import JsonValue, canonical_digest, freeze_json


class ToolRiskClass(StrEnum):
    OBSERVE = "observe"
    MUTATE = "mutate"
    HIGH_RISK = "high_risk"


@dataclass(frozen=True, slots=True)
class ToolArguments:
    values: tuple[tuple[str, JsonValue], ...] = ()

    @classmethod
    def from_mapping(cls, values: Mapping[str, JsonValue]) -> ToolArguments:
        if not isinstance(values, Mapping):
            raise TypeError("tool arguments must be a mapping")
        return cls(tuple(sorted((key, freeze_json(value)) for key, value in values.items())))

    def __post_init__(self) -> None:
        if type(self.values) is not tuple or any(
            type(row) is not tuple or len(row) != 2 for row in self.values
        ):
            raise TypeError("tool argument values must be key/value tuples")
        normalized = []
        for key, value in self.values:
            if type(key) is not str or not key.strip():
                raise ValueError("tool argument keys must be non-empty strings")
            normalized.append((key, freeze_json(value)))
        keys = [key for key, _value in normalized]
        if len(keys) != len(set(keys)):
            raise ValueError("tool argument keys must be unique")
        object.__setattr__(self, "values", tuple(sorted(normalized)))

    def as_mapping(self) -> dict[str, JsonValue]:
        return dict(self.values)

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema_id: str
    capability_id: str = ""
    risk_class: ToolRiskClass = ToolRiskClass.OBSERVE
    sandbox_profile: str = "reference"
    definition_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if any(
            type(value) is not str or not value.strip()
            for value in (self.name, self.description, self.input_schema_id, self.sandbox_profile)
        ):
            raise ValueError("tool definition text fields must be non-empty strings")
        if type(self.capability_id) is not str:
            raise TypeError("tool definition capability_id must be a string")
        if not isinstance(self.risk_class, ToolRiskClass):
            raise TypeError("tool definition risk_class is invalid")
        if self.risk_class is ToolRiskClass.HIGH_RISK and not self.capability_id.strip():
            raise ValueError("high-risk tools require an explicit capability_id")
        if self.capability_id and not self.capability_id.strip():
            raise ValueError("tool capability_id must be non-empty when present")
        object.__setattr__(
            self,
            "definition_digest",
            canonical_digest({
                "name": self.name,
                "description": self.description,
                "input_schema_id": self.input_schema_id,
                "capability_id": self.capability_id,
                "risk_class": self.risk_class.value,
                "sandbox_profile": self.sandbox_profile,
            }),
        )


@dataclass(frozen=True, slots=True)
class ToolAuthorization:
    capability_id: str
    approved: bool
    reason: str
    approval_id: str = ""

    def __post_init__(self) -> None:
        if (
            type(self.capability_id) is not str
            or type(self.reason) is not str
            or type(self.approved) is not bool
            or type(self.approval_id) is not str
        ):
            raise TypeError("tool authorization fields are invalid")
        if not self.capability_id.strip() or not self.reason.strip():
            raise ValueError("tool authorization capability and reason are required")
        if self.approved and not self.approval_id.strip():
            raise ValueError("approved tool authorization requires an approval_id")


class ToolAuthorizationPort(Protocol):
    def review(
        self, definition: ToolDefinition, arguments: ToolArguments
    ) -> ToolAuthorization: ...


class ToolAuditPort(Protocol):
    def record(
        self,
        definition: ToolDefinition,
        arguments: ToolArguments,
        result: "ToolResult",
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool_name: str
    success: bool
    content: str
    error: str | None = None
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.tool_name) is not str or not self.tool_name.strip() or type(self.success) is not bool:
            raise TypeError("tool result identity/success are invalid")
        if type(self.content) is not str:
            raise TypeError("tool result content must be string")
        if self.error is not None and type(self.error) is not str:
            raise TypeError("tool result error must be string or None")
        if self.success and self.error is not None:
            raise ValueError("successful tool result cannot carry an error")
        object.__setattr__(
            self,
            "result_digest",
            canonical_digest({
                "tool_name": self.tool_name,
                "success": self.success,
                "content": self.content,
                "error": self.error,
            }),
        )


ToolHandler = Callable[[ToolArguments], ToolResult]



class ToolRegistry:
    """Explicit per-method capability registry; no ambient lookup is possible."""

    def __init__(
        self,
        *,
        authorization: ToolAuthorizationPort | None = None,
        audit: ToolAuditPort | None = None,
    ) -> None:
        if authorization is not None and not callable(getattr(authorization, "review", None)):
            raise TypeError("tool authorization must implement review()")
        if audit is not None and not callable(getattr(audit, "record", None)):
            raise TypeError("tool audit must implement record()")
        self._handlers: dict[str, tuple[ToolDefinition, ToolHandler]] = {}
        self._authorization = authorization
        self._audit = audit
        self._lock = RLock()

    def register(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        if type(definition) is not ToolDefinition or not callable(handler):
            raise TypeError("tool registry requires a ToolDefinition and callable handler")
        with self._lock:
            if definition.name in self._handlers:
                raise ValueError(f"tool already registered: {definition.name}")
            self._handlers[definition.name] = (definition, handler)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        with self._lock:
            values = tuple(self._handlers.values())
        return tuple(
            row[0] for row in sorted(values, key=lambda row: row[0].name)
        )

    def invoke(self, name: str, arguments: ToolArguments) -> ToolResult:
        if type(name) is not str or not name.strip():
            raise ValueError("tool name must be non-empty")
        if type(arguments) is not ToolArguments:
            raise TypeError("tool invocation requires ToolArguments")
        with self._lock:
            entry = self._handlers.get(name)
        if entry is None:
            return ToolResult(name, False, "", f"unknown tool: {name}")
        definition, handler = entry
        authorization_error = self._authorization_error(definition, arguments)
        if authorization_error is not None:
            result = ToolResult(name, False, "", authorization_error)
            self._audit_result(definition, arguments, result)
            return result
        try:
            result = handler(arguments)
        except Exception as exc:
            result = ToolResult(name, False, "", f"{type(exc).__name__}: {exc}")
        if type(result) is not ToolResult or result.tool_name != name:
            raise RuntimeError("tool handler returned an invalid or foreign ToolResult")
        self._audit_result(definition, arguments, result)
        return result

    def _authorization_error(
        self, definition: ToolDefinition, arguments: ToolArguments
    ) -> str | None:
        if definition.risk_class is not ToolRiskClass.HIGH_RISK:
            return None
        if self._authorization is None:
            return "high-risk tool denied: explicit authorization is required"
        try:
            authorization = self._authorization.review(definition, arguments)
        except Exception as exc:
            return f"high-risk tool denied: authorization failed ({type(exc).__name__})"
        if type(authorization) is not ToolAuthorization:
            return "high-risk tool denied: authorization returned an invalid decision"
        if not authorization.approved:
            return f"high-risk tool denied: {authorization.reason}"
        if authorization.capability_id != definition.capability_id:
            return "high-risk tool denied: capability identity mismatch"
        return None

    def _audit_result(
        self,
        definition: ToolDefinition,
        arguments: ToolArguments,
        result: ToolResult,
    ) -> None:
        if self._audit is not None:
            self._audit.record(definition, arguments, result)


__all__ = [
    "ToolArguments", "ToolAuditPort", "ToolAuthorization",
    "ToolAuthorizationPort", "ToolDefinition", "ToolHandler", "ToolRegistry",
    "ToolResult", "ToolRiskClass",
]
