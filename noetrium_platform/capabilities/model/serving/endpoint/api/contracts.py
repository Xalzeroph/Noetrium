from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Mapping, Protocol
from urllib.parse import urlparse

from noetrium_platform.capabilities.model.request.api import (
    ModelEndpointEnvelope, ModelOperationEnvelope, ModelRequestEnvelope,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest, freeze_json, JsonInput, JsonValue

from .streaming import SseHttpResponse


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class ModelEndpointRequest:
    """One request sent to an exact deployment endpoint."""

    request: ModelEndpointEnvelope
    deployment_id: str
    deployment_generation: str
    body: Mapping[str, JsonInput]
    timeout_s: float | None = field(
        default=None,
        repr=False,
        compare=False,
        metadata={"transient": True},
    )
    _digest: str = field(
        init=False,
        repr=False,
        compare=False,
        metadata={"transient": True},
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.request,
            (ModelRequestEnvelope, ModelOperationEnvelope),
        ):
            raise TypeError(
                "model endpoint request must carry a model request/operation envelope"
            )
        if not isinstance(self.deployment_id, str) or not self.deployment_id.strip():
            raise ValueError("model endpoint deployment_id is required")
        _require_sha256(self.deployment_generation, "model endpoint deployment_generation")
        if not isinstance(self.body, Mapping):
            raise TypeError("model endpoint request body must be a mapping")
        if self.timeout_s is not None and (
            isinstance(self.timeout_s, bool)
            or not isinstance(self.timeout_s, (int, float))
            or not math.isfinite(float(self.timeout_s))
            or float(self.timeout_s) <= 0
        ):
            raise ValueError(
                "model endpoint request timeout_s must be finite and positive"
            )
        object.__setattr__(
            self, "body", freeze_json(self.body)
        )
        object.__setattr__(
            self,
            "_digest",
            canonical_digest({
                "request_envelope": self.request.envelope_digest,
                "deployment_id": self.deployment_id,
                "deployment_generation": self.deployment_generation,
                "body": self.body,
            }),
        )

    def digest(self) -> str:
        return self._digest


@dataclass(frozen=True, slots=True)
class ModelEndpointRoute:
    """Operational route bound to one exact deployment identity."""

    deployment_id: str
    deployment_generation: str
    base_url: str
    completion_path: str = "/v1/chat/completions"
    timeout_s: float = 120.0

    def __post_init__(self) -> None:
        if not isinstance(self.deployment_id, str) or not self.deployment_id.strip():
            raise ValueError("model endpoint route requires exact deployment identity")
        try:
            _require_sha256(self.deployment_generation, "model endpoint route deployment_generation")
        except ValueError as exc:
            raise ValueError("model endpoint route requires exact deployment identity") from exc
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("model endpoint route base_url must be an absolute HTTP(S) URL")
        if not self.completion_path.startswith("/"):
            raise ValueError("model endpoint completion_path must be absolute")
        if (
            isinstance(self.timeout_s, bool)
            or not isinstance(self.timeout_s, (int, float))
            or not math.isfinite(float(self.timeout_s))
            or self.timeout_s <= 0
        ):
            raise ValueError("model endpoint timeout_s must be finite and positive")

    @property
    def completion_url(self) -> str:
        return self.base_url.rstrip("/") + self.completion_path


@dataclass(frozen=True, slots=True)
class JsonHttpResponse:
    """Parsed response with exact wire evidence and response metadata."""

    status_code: int
    body: JsonValue
    raw_body: bytes = b""
    request_body: bytes = b""
    response_headers: tuple[tuple[str, str], ...] = ()
    http_version: str | None = None
    transport_digest: str | None = None

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise ValueError("HTTP status code is invalid")
        if type(self.raw_body) is not bytes or type(self.request_body) is not bytes:
            raise TypeError("HTTP wire bodies must be exact bytes")
        if type(self.response_headers) is not tuple or any(
            type(row) is not tuple
            or len(row) != 2
            or any(type(value) is not str or not value for value in row)
            for row in self.response_headers
        ):
            raise TypeError("HTTP response headers must be text pairs")
        object.__setattr__(
            self,
            "response_headers",
            tuple((name.lower(), value) for name, value in self.response_headers),
        )
        if self.http_version is not None and (
            type(self.http_version) is not str or not self.http_version.strip()
        ):
            raise ValueError("HTTP response version must be non-empty text or None")
        if self.transport_digest is not None:
            _require_sha256(
                self.transport_digest,
                "HTTP response transport_digest",
            )
        object.__setattr__(self, "body", freeze_json(self.body))

    def header(self, name: str) -> str | None:
        if type(name) is not str or not name.strip():
            raise ValueError("HTTP response header name is required")
        target = name.strip().lower()
        for key, value in self.response_headers:
            if key == target:
                return value
        return None


class ModelEndpointObserverPort(Protocol):
    """Non-authoritative hook for lossless model request/response capture."""

    observer_id: str

    def on_exchange(
        self,
        request: ModelEndpointRequest,
        response: JsonHttpResponse,
        started_monotonic_ns: int,
        completed_monotonic_ns: int,
    ) -> None:
        ...

    def on_stream_exchange(
        self,
        request: ModelEndpointRequest,
        response: SseHttpResponse,
        started_monotonic_ns: int,
        completed_monotonic_ns: int,
    ) -> None:
        ...

    def on_failure(
        self,
        request: ModelEndpointRequest,
        error: "ModelEndpointError",
        started_monotonic_ns: int,
        completed_monotonic_ns: int,
    ) -> None:
        ...


@dataclass(frozen=True, slots=True)
class ModelEndpointResponse:
    """Provider-neutral transport result for any model capability."""

    request_id: str
    deployment_id: str
    text: str = ""
    payload: JsonValue | None = None
    tool_calls: JsonValue = ()
    content_blocks: JsonValue = ()
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    usage: JsonValue | None = None
    response_digest: str = ""

    def __post_init__(self) -> None:
        if not self.request_id.strip() or not self.deployment_id.strip():
            raise ValueError("model endpoint response identity is required")
        if not isinstance(self.text, str):
            raise TypeError("model endpoint response text must be text")
        if self.payload is not None:
            object.__setattr__(self, "payload", freeze_json(self.payload))
        object.__setattr__(self, "tool_calls", freeze_json(self.tool_calls))
        object.__setattr__(self, "content_blocks", freeze_json(self.content_blocks))
        if not isinstance(self.tool_calls, tuple):
            raise TypeError("model endpoint response tool_calls must be a tuple")
        if not isinstance(self.content_blocks, tuple):
            raise TypeError("model endpoint response content_blocks must be a tuple")
        for block in self.content_blocks:
            if not isinstance(block, Mapping):
                raise TypeError("model endpoint content block must be an object")
            kind = block.get("kind")
            if type(kind) is not str or not kind.strip():
                raise ValueError("model endpoint content block kind is required")
        if (
            not self.text.strip()
            and not self.tool_calls
            and not self.content_blocks
            and self.payload is None
        ):
            raise ValueError("model endpoint response must contain canonical content")
        for name in ("input_tokens", "output_tokens"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be non-negative")
        if self.usage is not None:
            object.__setattr__(self, "usage", freeze_json(self.usage))
            if not isinstance(self.usage, Mapping):
                raise TypeError("model endpoint response usage must be a mapping")
        expected = canonical_digest({
            "request_id": self.request_id,
            "deployment_id": self.deployment_id,
            "text": self.text,
            "payload": self.payload,
            "tool_calls": self.tool_calls,
            "content_blocks": self.content_blocks,
            "finish_reason": self.finish_reason,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usage": self.usage,
        })
        if self.response_digest and self.response_digest != expected:
            raise ValueError("model endpoint response digest mismatch")
        object.__setattr__(self, "response_digest", expected)


class ModelEndpointError(RuntimeError):
    """Endpoint/transport failure with exact wire evidence when available."""

    affects_replica_health = True

    def __init__(
        self,
        message: str,
        *,
        request_body: bytes = b"",
        response_body: bytes = b"",
        status_code: int | None = None,
        response_headers: tuple[tuple[str, str], ...] = (),
        failure_kind: str = "unknown",
        retryable: bool = False,
        retry_after_seconds: float | None = None,
        provider_code: str | None = None,
        affects_replica_health: bool | None = None,
        http_version: str | None = None,
        transport_digest: str | None = None,
    ) -> None:
        super().__init__(message)
        if type(request_body) is not bytes or type(response_body) is not bytes:
            raise TypeError("model endpoint error wire bodies must be exact bytes")
        if status_code is not None and (
            type(status_code) is not int or not 100 <= status_code <= 599
        ):
            raise ValueError("model endpoint error HTTP status must be in [100, 599]")
        if type(response_headers) is not tuple or any(
            type(row) is not tuple
            or len(row) != 2
            or any(type(value) is not str or not value for value in row)
            for row in response_headers
        ):
            raise TypeError("model endpoint error response_headers must be text pairs")
        if type(failure_kind) is not str or not failure_kind.strip():
            raise ValueError("model endpoint error failure_kind is required")
        if type(retryable) is not bool:
            raise TypeError("model endpoint error retryable must be bool")
        if retry_after_seconds is not None and (
            isinstance(retry_after_seconds, bool)
            or not isinstance(retry_after_seconds, (int, float))
            or not math.isfinite(float(retry_after_seconds))
            or float(retry_after_seconds) < 0
        ):
            raise ValueError("model endpoint retry_after_seconds must be finite and non-negative")
        if provider_code is not None and (
            type(provider_code) is not str or not provider_code.strip()
        ):
            raise ValueError("model endpoint provider_code must be non-empty text or None")
        if affects_replica_health is not None and type(affects_replica_health) is not bool:
            raise TypeError("affects_replica_health must be bool or None")
        if http_version is not None and (
            type(http_version) is not str or not http_version.strip()
        ):
            raise ValueError("model endpoint error http_version must be text or None")
        if transport_digest is not None:
            _require_sha256(
                transport_digest,
                "model endpoint error transport_digest",
            )
        self.request_body = request_body
        self.response_body = response_body
        self.status_code = status_code
        self.response_headers = tuple(
            (name.lower(), value) for name, value in response_headers
        )
        self.failure_kind = failure_kind.strip()
        self.retryable = retryable
        self.retry_after_seconds = (
            None if retry_after_seconds is None else float(retry_after_seconds)
        )
        self.provider_code = provider_code
        self.http_version = http_version
        self.transport_digest = transport_digest
        self.affects_replica_health = (
            type(self).affects_replica_health
            if affects_replica_health is None
            else affects_replica_health
        )


class ModelEndpointRequestRejected(ModelEndpointError):
    """Request-level rejection that must not poison replica health."""

    affects_replica_health = False


__all__ = [
    "JsonHttpResponse",
    "ModelEndpointError", "ModelEndpointRequestRejected", "ModelEndpointObserverPort",
    "ModelEndpointRequest",
    "ModelEndpointResponse",
    "ModelEndpointRoute",
]
