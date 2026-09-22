from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from ..api.diagnostics import RunDiagnosticsPort
from ..api.artifacts import RunArtifactKind, RunArtifactStorePort
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.foundation.kernel.kernel import JsonValue


def json_default(value: object) -> object:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    return repr(value)


def exception_chain(exception: BaseException) -> tuple[dict[str, str], ...]:
    chain: list[dict[str, str]] = []
    current: BaseException | None = exception
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        descriptor = describe_exception(current)
        chain.append({
            "type": descriptor.qualified_type,
            "message": descriptor.safe_message,
            "error_digest": descriptor.error_digest,
        })
        current = current.__cause__ or current.__context__
    return tuple(chain)


class JsonlRunDiagnostics(RunDiagnosticsPort):
    """Platform implementation of the run diagnostics interface."""

    def __init__(self, artifacts: RunArtifactStorePort, *, run_id: str = "") -> None:
        self._artifacts = artifacts
        self.run_id = run_id
        self._sequence = 0
        self._sequence_lock = threading.Lock()

    def _envelope(self, kind: str) -> dict[str, object]:
        with self._sequence_lock:
            self._sequence += 1
            sequence = self._sequence
        return {
            "kind": kind,
            "run_id": self.run_id,
            "diagnostic_sequence": sequence,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

    def event(
        self,
        event: str = "",
        *,
        phase: str = "workload",
        attributes: Mapping[str, JsonValue] | None = None,
        level: str = "DEBUG",
        correlation_refs: tuple[str, ...] = (),
    ) -> None:
        row = self._envelope("event")
        row.update(
            {
                "phase": phase,
                "event": event,
                "level": level,
                "attributes": dict(attributes or {}),
                "correlation_refs": tuple(str(item) for item in correlation_refs),
            }
        )
        self._artifacts.append_json("events.jsonl", row, kind=RunArtifactKind.LOG)

    def metric(
        self,
        name: str = "",
        value: float = 0.0,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        row = self._envelope("metric")
        row.update({"name": name, "value": float(value), "labels": dict(labels or {})})
        self._artifacts.append_json("metrics.jsonl", row, kind=RunArtifactKind.LOG)

    def failure(
        self,
        code: str = "",
        message: str = "",
        *,
        phase: str = "workload",
        exception: BaseException | None = None,
        attributes: Mapping[str, JsonValue] | None = None,
        correlation_refs: tuple[str, ...] = (),
    ) -> None:
        row = self._envelope("failure")
        row.update(
            {
                "phase": phase,
                "code": code,
                "message": message,
                "exception_type": type(exception).__name__ if exception is not None else None,
                "attributes": dict(attributes or {}),
                "correlation_refs": tuple(str(item) for item in correlation_refs),
            }
        )
        if exception is not None:
            row["cause_chain"] = exception_chain(exception)
            descriptor = describe_exception(exception)
            row["exception"] = {
                "type": descriptor.qualified_type,
                "message": descriptor.safe_message,
                "error_digest": descriptor.error_digest,
            }
        self._artifacts.append_json("failures.jsonl", row, kind=RunArtifactKind.LOG)


__all__ = ["JsonlRunDiagnostics", "exception_chain", "json_default"]
