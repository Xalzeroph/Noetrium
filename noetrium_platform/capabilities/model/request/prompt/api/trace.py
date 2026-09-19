from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Protocol


class PromptTraceStage(StrEnum):
    REQUEST_CREATED = "request_created"
    COMPILE_STARTED = "compile_started"
    COMPILE_COMPLETED = "compile_completed"
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    HEADERS_RECEIVED = "headers_received"
    FIRST_BYTE = "first_byte"
    FIRST_TOKEN = "first_token"
    RESPONSE_COMPLETED = "response_completed"
    PARSE_COMPLETED = "parse_completed"
    SCHEMA_VALIDATED = "schema_validated"
    OUTCOME_LINKED = "outcome_linked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PromptTraceDescriptor:
    request_id: str
    role: str
    model: str
    request_digest: str
    bundle: str


@dataclass(frozen=True, slots=True)
class PromptTracePoint:
    stage: PromptTraceStage
    timestamp: float
    details: tuple[tuple[str, object], ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.timestamp, bool)
            or not isinstance(self.timestamp, (int, float))
            or not math.isfinite(float(self.timestamp))
            or self.timestamp < 0
        ):
            raise ValueError("prompt trace timestamp must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class PromptTraceSummary:
    request_id: str
    role: str
    model: str
    request_digest: str
    points: tuple[PromptTracePoint, ...]
    total_seconds: float
    compile_seconds: float | None
    queue_seconds: float | None
    headers_seconds: float | None
    first_byte_seconds: float | None
    ttft_seconds: float | None
    parse_seconds: float | None
    schema_seconds: float | None
    failed_stage: str | None

    def __post_init__(self) -> None:
        for field in ("total_seconds", "compile_seconds", "queue_seconds", "headers_seconds", "first_byte_seconds", "ttft_seconds", "parse_seconds", "schema_seconds"):
            value = getattr(self, field)
            if value is None:
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value < 0
            ):
                raise ValueError(f"prompt trace {field} must be finite and non-negative")


class PromptTraceObserverPort(Protocol):
    """Side-plane observer for immutable prompt trace facts."""

    def point_recorded(self, descriptor: PromptTraceDescriptor, point: PromptTracePoint) -> None: ...

    def summary_recorded(
        self,
        descriptor: PromptTraceDescriptor,
        summary: PromptTraceSummary,
        *,
        status: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PromptTraceObserverFailure:
    stage: str
    error_type: str

    @classmethod
    def from_exception(cls, stage: str, exc: BaseException) -> "PromptTraceObserverFailure":
        return cls(stage=stage, error_type=type(exc).__qualname__)


class PromptTraceObserverFailureSink(Protocol):
    def record(self, failure: PromptTraceObserverFailure) -> None: ...


__all__ = [
    "PromptTraceDescriptor",
    "PromptTraceObserverFailure",
    "PromptTraceObserverFailureSink",
    "PromptTraceObserverPort",
    "PromptTracePoint",
    "PromptTraceStage",
    "PromptTraceSummary",
]
