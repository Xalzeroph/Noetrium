from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite

from noetrium_platform.foundation.kernel.kernel import JsonInput, JsonValue


class _FrozenJsonObject(dict[str, JsonValue]):
    @staticmethod
    def _immutable(*_args: object, **_kwargs: object) -> None:
        raise TypeError("diagnostic record payload is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _freeze_json(value: JsonInput, *, path: str) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"non-finite diagnostic JSON number at {path}")
        return value
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    if isinstance(value, Mapping):
        frozen: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"diagnostic JSON key at {path} must be a string")
            frozen[key] = _freeze_json(item, path=f"{path}.{key}")
        return _FrozenJsonObject(frozen)
    raise TypeError(f"unsupported diagnostic JSON value at {path}: {type(value).__name__}")


def freeze_diagnostic_mapping(payload: Mapping[str, JsonInput]) -> Mapping[str, JsonValue]:
    frozen = _freeze_json(payload, path="payload")
    if not isinstance(frozen, Mapping):
        raise TypeError("diagnostic payload must be an object")
    return frozen


def _thaw_json(value: JsonValue) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _payload_copy(payload: Mapping[str, JsonValue]) -> dict[str, object]:
    return {key: _thaw_json(value) for key, value in payload.items()}


_OBJECT_ID_FIELDS = {"event": "event_id", "failure": "failure_id", "mutation": "mutation_id"}

@dataclass(frozen=True, slots=True)
class DiagnosticObjectRecord:
    object_id: str
    kind: str
    run_id: str | None
    task_id: str | None
    decision_cycle_id: str | None
    trace_id: str | None
    span_id: str | None
    component_id: str | None
    timestamp: float | None
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        if not self.object_id:
            raise ValueError("diagnostic object_id cannot be empty")
        id_field = _OBJECT_ID_FIELDS.get(self.kind)
        if id_field is None:
            raise ValueError(f"unsupported diagnostic object kind: {self.kind!r}")
        if self.timestamp is not None and not isfinite(self.timestamp):
            raise ValueError("diagnostic object timestamp must be finite")
        frozen = freeze_diagnostic_mapping(self.payload)
        if frozen.get(id_field) != self.object_id:
            raise ValueError("diagnostic object projection identity disagrees with payload")
        object.__setattr__(self, "payload", frozen)

    def to_payload(self) -> dict[str, object]:
        return _payload_copy(self.payload)


@dataclass(frozen=True, slots=True)
class StateWriterRecord:
    mutation_id: str
    state_name: str
    run_id: str
    task_id: str | None
    decision_cycle_id: str | None
    trace_id: str | None
    span_id: str | None
    component_id: str
    operation_id: str
    new_version: int
    new_digest: str
    timestamp: float
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        if not self.mutation_id or not self.state_name or not self.run_id:
            raise ValueError("state-writer identity fields cannot be empty")
        if not self.component_id or not self.operation_id:
            raise ValueError("state-writer component/operation cannot be empty")
        if self.new_version < 0:
            raise ValueError("state-writer new_version cannot be negative")
        if not isfinite(self.timestamp):
            raise ValueError("state-writer timestamp must be finite")
        frozen = freeze_diagnostic_mapping(self.payload)
        expected = (frozen.get("mutation_id"), frozen.get("state_name"), frozen.get("operation_id"))
        if expected != (self.mutation_id, self.state_name, self.operation_id):
            raise ValueError("state-writer projection identity disagrees with payload")
        object.__setattr__(self, "payload", frozen)

    def to_payload(self) -> dict[str, object]:
        return _payload_copy(self.payload)


@dataclass(frozen=True, slots=True)
class OperationInvocationRecord:
    invocation_id: str
    operation_id: str
    operation_type: str
    run_id: str | None
    task_id: str | None
    decision_cycle_id: str | None
    trace_id: str | None
    span_id: str | None
    caller_component_id: str | None
    target_component_id: str | None
    started_event_id: str | None
    started_at: float | None
    terminal_event_id: str | None
    terminal_event_type: str | None
    terminal_at: float | None
    status: str | None
    failure_id: str | None
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        if not self.invocation_id or not self.operation_id or not self.operation_type:
            raise ValueError("operation invocation identity fields cannot be empty")
        for value in (self.started_at, self.terminal_at):
            if value is not None and not isfinite(value):
                raise ValueError("operation invocation timestamps must be finite")
        if self.started_at is not None and self.terminal_at is not None and self.terminal_at < self.started_at:
            raise ValueError("operation invocation terminal_at precedes started_at")
        frozen = freeze_diagnostic_mapping(self.payload)
        event_payload = frozen.get("payload")
        if not isinstance(event_payload, Mapping):
            raise ValueError("operation invocation latest payload lacks event payload")
        identity = (
            event_payload.get("operation_invocation_id"),
            event_payload.get("operation_id"),
            event_payload.get("operation_type"),
        )
        if identity != (self.invocation_id, self.operation_id, self.operation_type):
            raise ValueError("operation invocation projection identity disagrees with payload")
        object.__setattr__(self, "payload", frozen)

    def to_payload(self) -> dict[str, object]:
        return _payload_copy(self.payload)

    def to_summary(self) -> dict[str, object]:
        return {
            "invocation_id": self.invocation_id,
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "decision_cycle_id": self.decision_cycle_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "caller_component_id": self.caller_component_id,
            "target_component_id": self.target_component_id,
            "started_event_id": self.started_event_id,
            "started_at": self.started_at,
            "terminal_event_id": self.terminal_event_id,
            "terminal_event_type": self.terminal_event_type,
            "terminal_at": self.terminal_at,
            "status": self.status,
            "failure_id": self.failure_id,
        }


__all__ = ["DiagnosticObjectRecord", "OperationInvocationRecord", "StateWriterRecord", "freeze_diagnostic_mapping"]
