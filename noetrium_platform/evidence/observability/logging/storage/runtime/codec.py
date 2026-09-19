from __future__ import annotations

import json

from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.evidence.observability.logging.context.api import DiagnosticAddress
from noetrium_platform.evidence.observability.logging.record.api import LogLevel, LogRecord
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind


LOG_RECORD_SCHEMA_VERSION = "noetrium.log-record.v1"


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"durable log JSON forbids non-finite constant {value}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError(f"durable log JSON contains duplicate key {key!r}")
        document[key] = value
    return document


def decode_log_line(line: str) -> LogRecord:
    document = json.loads(
        line,
        parse_constant=_reject_json_constant,
        object_pairs_hook=_unique_object,
    )
    return decode_log_record(document)


def _require_object(value: object, *, label: str, fields: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise TypeError(f"{label} must be an object with string keys")
    if set(value) != fields:
        raise ValueError(f"{label} fields do not match the durable schema")
    return value


def _require_string(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    return value


def _optional_string(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, label=label)


def _string_list(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be a list")
    return tuple(_require_string(item, label=f"{label} item") for item in value)


def encode_log_record(record: LogRecord) -> dict[str, object]:
    return {
        "schema_version": LOG_RECORD_SCHEMA_VERSION,
        "log_id": record.log_id,
        "created_at": record.created_at,
        "level": record.level.value,
        "logger": record.logger,
        "event": record.event,
        "message": record.message,
        "address": {
            "scope_path": [
                {"kind": item.kind.value, "scope_id": item.scope_id}
                for item in record.address.scope_path
            ],
            "system_path": [
                {"system_id": item.system_id, "subsystem_path": list(item.subsystem_path)}
                for item in record.address.system_path
            ],
            "component_id": record.address.component_id,
            "operation_id": record.address.operation_id,
            "trace_id": record.address.trace_id,
            "span_id": record.address.span_id,
        },
        "attributes": [list(item) for item in record.attributes],
        "exception": None if record.exception is None else {
            "error_type": record.exception.error_type,
            "qualified_type": record.exception.qualified_type,
            "safe_message": record.exception.safe_message,
            "error_digest": record.exception.error_digest,
        },
        "correlation_refs": list(record.correlation_refs),
        "failure_refs": list(record.failure_refs),
        "artifact_refs": list(record.artifact_refs),
    }


def decode_log_record(document: object) -> LogRecord:
    row = _require_object(
        document,
        label="log line",
        fields=frozenset({
            "schema_version", "log_id", "created_at", "level", "logger", "event",
            "message", "address", "attributes", "exception", "correlation_refs",
            "failure_refs", "artifact_refs",
        }),
    )
    if row["schema_version"] != LOG_RECORD_SCHEMA_VERSION:
        raise ValueError("unsupported JSONL log schema_version")

    address = _require_object(
        row["address"],
        label="log address",
        fields=frozenset({
            "scope_path", "system_path", "component_id", "operation_id", "trace_id", "span_id",
        }),
    )
    raw_scopes = address["scope_path"]
    if not isinstance(raw_scopes, list):
        raise TypeError("log address scope_path must be a list")
    scopes: list[ScopeIdentity] = []
    for raw_scope in raw_scopes:
        scope = _require_object(
            raw_scope,
            label="log scope identity",
            fields=frozenset({"kind", "scope_id"}),
        )
        scopes.append(
            ScopeIdentity(
                ScopeKind(_require_string(scope["kind"], label="scope kind")),
                _require_string(scope["scope_id"], label="scope_id"),
            )
        )

    raw_systems = address["system_path"]
    if not isinstance(raw_systems, list):
        raise TypeError("log address system_path must be a list")
    systems: list[SystemIdentity] = []
    for raw_system in raw_systems:
        system = _require_object(
            raw_system,
            label="log system identity",
            fields=frozenset({"system_id", "subsystem_path"}),
        )
        systems.append(
            SystemIdentity(
                _require_string(system["system_id"], label="system_id"),
                _string_list(system["subsystem_path"], label="subsystem_path"),
            )
        )

    raw_attributes = row["attributes"]
    if not isinstance(raw_attributes, list):
        raise TypeError("log attributes must be a list")
    attributes: list[tuple[str, str]] = []
    for item in raw_attributes:
        if not isinstance(item, list) or len(item) != 2:
            raise TypeError("each log attribute must be a two-item list")
        attributes.append(
            (
                _require_string(item[0], label="log attribute key"),
                _require_string(item[1], label="log attribute value"),
            )
        )

    exception = row["exception"]
    descriptor = None
    if exception is not None:
        from noetrium_platform.foundation.kernel.kernel.errors.contracts import SafeExceptionDescriptor

        exception_row = _require_object(
            exception,
            label="log exception",
            fields=frozenset({"error_type", "qualified_type", "safe_message", "error_digest"}),
        )
        descriptor = SafeExceptionDescriptor(
            _require_string(exception_row["error_type"], label="exception error_type"),
            _require_string(exception_row["qualified_type"], label="exception qualified_type"),
            _require_string(exception_row["safe_message"], label="exception safe_message"),
            _require_string(exception_row["error_digest"], label="exception error_digest"),
        )

    created_at = row["created_at"]
    if type(created_at) not in {int, float}:
        raise TypeError("log created_at must be a number")
    return LogRecord(
        log_id=_require_string(row["log_id"], label="log_id"),
        created_at=float(created_at),
        level=LogLevel(_require_string(row["level"], label="log level")),
        logger=_require_string(row["logger"], label="logger"),
        event=_require_string(row["event"], label="event"),
        message=_require_string(row["message"], label="message"),
        address=DiagnosticAddress(
            scope_path=tuple(scopes),
            system_path=tuple(systems),
            component_id=_optional_string(address["component_id"], label="component_id"),
            operation_id=_optional_string(address["operation_id"], label="operation_id"),
            trace_id=_optional_string(address["trace_id"], label="trace_id"),
            span_id=_optional_string(address["span_id"], label="span_id"),
        ),
        attributes=tuple(attributes),
        exception=descriptor,
        correlation_refs=_string_list(row["correlation_refs"], label="correlation_refs"),
        failure_refs=_string_list(row["failure_refs"], label="failure_refs"),
        artifact_refs=_string_list(row["artifact_refs"], label="artifact_refs"),
    )


__all__ = [
    "LOG_RECORD_SCHEMA_VERSION",
    "decode_log_line",
    "decode_log_record",
    "encode_log_record",
]
