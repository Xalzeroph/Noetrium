from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from noetrium_platform.foundation.kernel.kernel import (
    JsonInput,
    JsonValue,
    canonical_digest,
    freeze_json,
)


class ModelStreamEventKind(str, Enum):
    TEXT_DELTA = "text_delta"
    REASONING_DELTA = "reasoning_delta"
    TOOL_CALL_DELTA = "tool_call_delta"
    CONTENT = "content"
    USAGE = "usage"
    RETRY = "retry"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RawServerSentEvent:
    event: str | None
    data: bytes
    event_id: str | None = None
    retry_ms: int | None = None
    raw_bytes: bytes = b""

    def __post_init__(self) -> None:
        if self.event is not None and (
            type(self.event) is not str or not self.event.strip()
        ):
            raise ValueError("SSE event name must be non-empty text or None")
        if type(self.data) is not bytes:
            raise TypeError("SSE data must be exact bytes")
        if self.event_id is not None and type(self.event_id) is not str:
            raise TypeError("SSE event id must be text or None")
        if self.retry_ms is not None and (
            type(self.retry_ms) is not int or self.retry_ms < 0
        ):
            raise ValueError("SSE retry_ms must be non-negative integer or None")
        if type(self.raw_bytes) is not bytes:
            raise TypeError("SSE raw_bytes must be exact bytes")


@dataclass(frozen=True, slots=True)
class ModelStreamEvent:
    kind: ModelStreamEventKind
    sequence: int
    provider_event_type: str
    provider_id: str
    attempt_number: int = 1
    text_delta: str = ""
    reasoning_delta: str = ""
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_arguments_delta: str = ""
    usage: JsonValue | None = None
    content: JsonValue | None = None
    terminal: bool = False
    event_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ModelStreamEventKind):
            raise TypeError("model stream event kind is invalid")
        for name in ("sequence", "attempt_number"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"model stream event {name} must be positive")
        for name in ("provider_event_type", "provider_id"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"model stream event {name} is required")
        for name in ("text_delta", "reasoning_delta", "tool_arguments_delta"):
            if type(getattr(self, name)) is not str:
                raise TypeError(f"model stream event {name} must be text")
        for name in ("tool_call_id", "tool_name"):
            value = getattr(self, name)
            if value is not None and (type(value) is not str or not value):
                raise ValueError(f"model stream event {name} must be text or None")
        if type(self.terminal) is not bool:
            raise TypeError("model stream event terminal must be bool")
        if self.usage is not None:
            object.__setattr__(self, "usage", freeze_json(self.usage))
            if not isinstance(self.usage, Mapping):
                raise TypeError("model stream usage must be an object")
        if self.content is not None:
            object.__setattr__(self, "content", freeze_json(self.content))
        object.__setattr__(
            self,
            "event_digest",
            canonical_digest(
                {
                    "schema": "noetrium.model-stream-event.v1",
                    "kind": self.kind.value,
                    "sequence": self.sequence,
                    "provider_event_type": self.provider_event_type,
                    "provider_id": self.provider_id,
                    "attempt_number": self.attempt_number,
                    "text_delta": self.text_delta,
                    "reasoning_delta": self.reasoning_delta,
                    "tool_call_id": self.tool_call_id,
                    "tool_name": self.tool_name,
                    "tool_arguments_delta": self.tool_arguments_delta,
                    "usage": self.usage,
                    "content": self.content,
                    "terminal": self.terminal,
                }
            ),
        )




@dataclass(frozen=True, slots=True)
class SseHttpResponse:
    status_code: int
    response_headers: tuple[tuple[str, str], ...]
    request_body: bytes
    raw_body: bytes
    event_count: int
    http_version: str | None = None
    transport_digest: str | None = None

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise ValueError("SSE HTTP status code is invalid")
        if type(self.response_headers) is not tuple or any(
            type(row) is not tuple
            or len(row) != 2
            or any(type(value) is not str or not value for value in row)
            for row in self.response_headers
        ):
            raise TypeError("SSE HTTP response headers must be text pairs")
        if type(self.request_body) is not bytes or type(self.raw_body) is not bytes:
            raise TypeError("SSE HTTP wire bodies must be exact bytes")
        if type(self.event_count) is not int or self.event_count < 0:
            raise ValueError("SSE HTTP event_count must be non-negative")
        if self.http_version is not None and (
            type(self.http_version) is not str or not self.http_version.strip()
        ):
            raise ValueError("SSE HTTP version must be non-empty text or None")
        if self.transport_digest is not None and (
            type(self.transport_digest) is not str
            or len(self.transport_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.transport_digest)
        ):
            raise ValueError("SSE transport_digest must be lowercase SHA-256 or None")
        object.__setattr__(
            self,
            "response_headers",
            tuple((name.lower(), value) for name, value in self.response_headers),
        )

    def header(self, name: str) -> str | None:
        if type(name) is not str or not name.strip():
            raise ValueError("SSE HTTP header name is required")
        target = name.strip().lower()
        for key, value in self.response_headers:
            if key == target:
                return value
        return None


class ServerSentEventDecoder:
    """Incremental RFC-compatible SSE framing with exact raw-byte retention."""

    def __init__(self, *, max_event_bytes: int = 4 * 1024 * 1024) -> None:
        if type(max_event_bytes) is not int or max_event_bytes <= 0:
            raise ValueError("SSE max_event_bytes must be positive")
        self._max_event_bytes = max_event_bytes
        self._buffer = bytearray()
        self._lines: list[bytes] = []

    def _emit(self) -> RawServerSentEvent | None:
        if not self._lines:
            return None
        raw = b"".join(self._lines) + b"\n"
        event: str | None = None
        event_id: str | None = None
        retry_ms: int | None = None
        data_rows: list[bytes] = []
        for line in self._lines:
            clean = line.rstrip(b"\r\n")
            if not clean or clean.startswith(b":"):
                continue
            if b":" in clean:
                field, value = clean.split(b":", 1)
                if value.startswith(b" "):
                    value = value[1:]
            else:
                field, value = clean, b""
            if field == b"event":
                event = value.decode("utf-8")
            elif field == b"data":
                data_rows.append(value)
            elif field == b"id":
                event_id = value.decode("utf-8")
            elif field == b"retry":
                try:
                    retry_ms = int(value)
                except ValueError:
                    retry_ms = None
        self._lines.clear()
        if not data_rows and event is None and event_id is None and retry_ms is None:
            return None
        data = b"\n".join(data_rows)
        return RawServerSentEvent(
            event=event,
            data=data,
            event_id=event_id,
            retry_ms=retry_ms,
            raw_bytes=raw,
        )

    def feed(self, chunk: bytes) -> tuple[RawServerSentEvent, ...]:
        if type(chunk) is not bytes:
            raise TypeError("SSE decoder chunk must be bytes")
        self._buffer.extend(chunk)
        if len(self._buffer) > self._max_event_bytes:
            raise ValueError("SSE buffered event exceeds configured limit")
        events: list[RawServerSentEvent] = []
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                break
            line = bytes(self._buffer[: newline + 1])
            del self._buffer[: newline + 1]
            if line in {b"\n", b"\r\n"}:
                event = self._emit()
                if event is not None:
                    events.append(event)
            else:
                self._lines.append(line)
                total = sum(len(row) for row in self._lines) + len(self._buffer)
                if total > self._max_event_bytes:
                    raise ValueError("SSE event exceeds configured limit")
        return tuple(events)

    def finish(self) -> tuple[RawServerSentEvent, ...]:
        if self._buffer:
            self._lines.append(bytes(self._buffer))
            self._buffer.clear()
        event = self._emit()
        return () if event is None else (event,)


__all__ = [
    "ModelStreamEvent",
    "ModelStreamEventKind",
    "RawServerSentEvent",
    "ServerSentEventDecoder",
    "SseHttpResponse",
]
