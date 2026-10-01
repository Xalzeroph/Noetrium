from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http.cookiejar import CookieJar, DefaultCookiePolicy
import json
import math
from threading import Lock

import httpx

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    AsyncJsonHttpTransportPort,
    AsyncJsonSseTransportPort,
    AsyncTextHttpTransportPort,
    JsonHttpResponse,
    ModelEndpointError,
    RawServerSentEvent,
    ServerSentEventDecoder,
    SseHttpResponse,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest


class _RejectAllCookiePolicy(DefaultCookiePolicy):
    def set_ok(self, cookie, request) -> bool:  # pragma: no cover - stdlib callback
        return False

    def return_ok(self, cookie, request) -> bool:  # pragma: no cover - stdlib callback
        return False


@dataclass(frozen=True, slots=True)
class PooledModelHttpTransportSnapshot:
    requests_started: int
    requests_completed: int
    requests_failed: int
    streams_started: int
    streams_completed: int
    streams_failed: int
    http1_responses: int
    http2_responses: int
    other_http_responses: int
    transport_digest: str


class PooledModelHttpTransport(
    AsyncJsonHttpTransportPort,
    AsyncJsonSseTransportPort,
    AsyncTextHttpTransportPort,
):
    """Single pooled HTTP transport for model provider traffic.

    The transport delegates only generic HTTP/1.1 + HTTP/2 connection
    management to HTTPX. Noetrium retains request serialization, retry policy,
    deadlines, SSE framing, provider semantics, evidence and resource lifetime.
    Hidden cookies, environment proxies and redirects are disabled.
    """

    def __init__(
        self,
        *,
        headers: tuple[tuple[str, str], ...] = (),
        max_connections: int = 256,
        max_keepalive_connections: int = 128,
        keepalive_expiry_s: float = 30.0,
        max_response_bytes: int = 32 * 1024 * 1024,
        max_sse_event_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        if type(headers) is not tuple or any(
            type(row) is not tuple
            or len(row) != 2
            or any(type(value) is not str or not value for value in row)
            for row in headers
        ):
            raise TypeError("model HTTP transport headers must be text pairs")
        for name, value in (
            ("max_connections", max_connections),
            ("max_keepalive_connections", max_keepalive_connections),
            ("max_response_bytes", max_response_bytes),
            ("max_sse_event_bytes", max_sse_event_bytes),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"model HTTP transport {name} must be positive integer")
        if max_keepalive_connections > max_connections:
            raise ValueError(
                "model HTTP max_keepalive_connections cannot exceed max_connections"
            )
        if (
            isinstance(keepalive_expiry_s, bool)
            or not isinstance(keepalive_expiry_s, (int, float))
            or not math.isfinite(float(keepalive_expiry_s))
            or float(keepalive_expiry_s) <= 0
        ):
            raise ValueError(
                "model HTTP keepalive_expiry_s must be finite and positive"
            )
        if max_sse_event_bytes > max_response_bytes:
            raise ValueError(
                "model HTTP max_sse_event_bytes cannot exceed max_response_bytes"
            )

        self._headers = (
            ("Content-Type", "application/json"),
            ("Accept-Encoding", "identity"),
            ("User-Agent", "noetrium-model-transport/1"),
            *headers,
        )
        self._max_response_bytes = max_response_bytes
        self._max_sse_event_bytes = max_sse_event_bytes
        self._state_lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._requests_started = 0
        self._requests_completed = 0
        self._requests_failed = 0
        self._streams_started = 0
        self._streams_completed = 0
        self._streams_failed = 0
        self._http1_responses = 0
        self._http2_responses = 0
        self._other_http_responses = 0

        cookie_jar = CookieJar(policy=_RejectAllCookiePolicy())
        self._client = httpx.AsyncClient(
            http1=True,
            http2=True,
            cookies=cookie_jar,
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
                keepalive_expiry=float(keepalive_expiry_s),
            ),
            # Request-scoped timeouts are authoritative.
            timeout=None,
            headers={
                "Accept-Encoding": "identity",
                "User-Agent": "noetrium-model-transport/1",
            },
        )
        self._transport_digest = canonical_digest(
            {
                "schema": "noetrium.pooled-model-http-transport.v1",
                "http1": True,
                "http2": True,
                "trust_env": False,
                "follow_redirects": False,
                "cookies": False,
                "max_connections": max_connections,
                "max_keepalive_connections": max_keepalive_connections,
                "keepalive_expiry_s": float(keepalive_expiry_s),
                "max_response_bytes": max_response_bytes,
                "max_sse_event_bytes": max_sse_event_bytes,
                "headers": tuple(name.lower() for name, _value in self._headers),
            }
        )

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        with self._state_lock:
            if self._closed:
                raise ModelEndpointError(
                    "model HTTP transport is closed",
                    failure_kind="internal",
                    retryable=False,
                    affects_replica_health=False,
                    transport_digest=self._transport_digest,
                )
            if self._loop is None:
                self._loop = loop
            elif self._loop is not loop:
                raise ModelEndpointError(
                    "model HTTP transport crossed ASYNC_IO event-loop ownership",
                    failure_kind="internal",
                    retryable=False,
                    affects_replica_health=False,
                )

    @staticmethod
    def _validate_timeout(value: float, field: str) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0
        ):
            raise ValueError(f"{field} must be finite and positive")
        return float(value)

    @staticmethod
    def _validate_headers(
        headers: tuple[tuple[str, str], ...],
    ) -> tuple[tuple[str, str], ...]:
        if type(headers) is not tuple or any(
            type(row) is not tuple
            or len(row) != 2
            or any(type(value) is not str or not value for value in row)
            for row in headers
        ):
            raise TypeError("model endpoint per-request headers must be text pairs")
        return headers

    def _request_headers(
        self,
        per_request: tuple[tuple[str, str], ...],
        *,
        accept: str,
    ) -> dict[str, str]:
        rows = {
            name: value
            for name, value in (*self._headers, *per_request)
        }
        rows["Accept"] = accept
        # HTTPX supplies Host/Content-Length and chooses protocol framing.
        rows.pop("Host", None)
        rows.pop("Content-Length", None)
        rows.pop("Connection", None)
        return rows

    def _record_http_version(self, version: str) -> None:
        with self._state_lock:
            if version == "HTTP/2":
                self._http2_responses += 1
            elif version == "HTTP/1.1":
                self._http1_responses += 1
            else:
                self._other_http_responses += 1

    @staticmethod
    def _response_headers(response: httpx.Response) -> tuple[tuple[str, str], ...]:
        return tuple(
            (str(name), str(value))
            for name, value in response.headers.multi_items()
        )

    async def _read_bounded_raw(
        self,
        response: httpx.Response,
        *,
        request_body: bytes = b"",
    ) -> bytes:
        parts: list[bytes] = []
        total = 0
        async for chunk in response.aiter_raw():
            total += len(chunk)
            if total > self._max_response_bytes:
                raise ModelEndpointError(
                    "model endpoint HTTP response exceeds configured limit",
                    request_body=request_body,
                    response_body=b"".join(parts),
                    failure_kind="invalid_request",
                    retryable=False,
                    affects_replica_health=False,
                    http_version=response.http_version,
                    transport_digest=self._transport_digest,
                )
            parts.append(chunk)
        return b"".join(parts)

    @staticmethod
    def _request_timeout(
        *,
        timeout_s: float,
        read_timeout_s: float | None = None,
    ) -> httpx.Timeout:
        return httpx.Timeout(
            timeout=timeout_s,
            connect=timeout_s,
            read=timeout_s if read_timeout_s is None else read_timeout_s,
            write=timeout_s,
            pool=timeout_s,
        )

    def _translate_httpx_error(
        self,
        exc: BaseException,
        *,
        request_body: bytes,
        response_body: bytes = b"",
    ) -> ModelEndpointError:
        if isinstance(exc, httpx.TimeoutException):
            return ModelEndpointError(
                f"model endpoint HTTP timeout: {type(exc).__name__}",
                request_body=request_body,
                response_body=response_body,
                failure_kind="timeout",
                retryable=True,
                affects_replica_health=True,
                transport_digest=self._transport_digest,
            )
        if isinstance(exc, httpx.TransportError):
            return ModelEndpointError(
                f"model endpoint HTTP transport failed: {type(exc).__name__}",
                request_body=request_body,
                response_body=response_body,
                failure_kind="transient",
                retryable=True,
                affects_replica_health=True,
                transport_digest=self._transport_digest,
            )
        raise TypeError("unexpected HTTPX exception classification")

    async def aclose(self) -> None:
        loop = asyncio.get_running_loop()
        with self._state_lock:
            if self._closed:
                return
            if self._loop is not None and self._loop is not loop:
                raise ModelEndpointError(
                    "model HTTP transport close crossed ASYNC_IO event-loop ownership",
                    failure_kind="internal",
                    retryable=False,
                    affects_replica_health=False,
                    transport_digest=self._transport_digest,
                )
            self._closed = True
            if self._loop is None:
                self._loop = loop
        await self._client.aclose()

    def snapshot(self) -> PooledModelHttpTransportSnapshot:
        with self._state_lock:
            return PooledModelHttpTransportSnapshot(
                requests_started=self._requests_started,
                requests_completed=self._requests_completed,
                requests_failed=self._requests_failed,
                streams_started=self._streams_started,
                streams_completed=self._streams_completed,
                streams_failed=self._streams_failed,
                http1_responses=self._http1_responses,
                http2_responses=self._http2_responses,
                other_http_responses=self._other_http_responses,
                transport_digest=self._transport_digest,
            )

    async def get_text(
        self,
        url: str,
        *,
        timeout_s: float,
        headers: tuple[tuple[str, str], ...] = (),
    ) -> str:
        self._bind_loop()
        timeout = self._validate_timeout(
            timeout_s,
            "model endpoint text HTTP timeout",
        )
        per_request = self._validate_headers(headers)
        with self._state_lock:
            self._requests_started += 1
        try:
            async with asyncio.timeout(timeout):
                async with self._client.stream(
                    "GET",
                    url,
                    headers=self._request_headers(
                        per_request,
                        accept="text/plain",
                    ),
                    timeout=self._request_timeout(timeout_s=timeout),
                ) as response:
                    raw = await self._read_bounded_raw(response)
                    version = response.http_version
                    status = response.status_code
        except ModelEndpointError:
            with self._state_lock:
                self._requests_failed += 1
            raise
        except TimeoutError as exc:
            with self._state_lock:
                self._requests_failed += 1
            raise ModelEndpointError(
                "model endpoint text HTTP total request timeout",
                failure_kind="timeout",
                retryable=True,
                affects_replica_health=False,
                transport_digest=self._transport_digest,
            ) from exc
        except httpx.HTTPError as exc:
            with self._state_lock:
                self._requests_failed += 1
            translated = self._translate_httpx_error(
                exc,
                request_body=b"",
            )
            translated.affects_replica_health = False
            raise translated from exc
        self._record_http_version(version)
        if not 200 <= status < 300:
            with self._state_lock:
                self._requests_failed += 1
            raise ModelEndpointError(
                f"model endpoint text HTTP status is not successful: {status}",
                response_body=raw,
                status_code=status,
                failure_kind="transient" if status >= 500 else "invalid_request",
                retryable=status >= 500,
                affects_replica_health=False,
                http_version=version,
                transport_digest=self._transport_digest,
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            with self._state_lock:
                self._requests_failed += 1
            raise ModelEndpointError(
                "model endpoint text HTTP response is not UTF-8",
                response_body=raw,
                status_code=status,
                failure_kind="invalid_request",
                retryable=False,
                affects_replica_health=False,
                http_version=version,
                transport_digest=self._transport_digest,
            ) from exc
        with self._state_lock:
            self._requests_completed += 1
        return text

    async def post_json(
        self,
        url: str,
        body: bytes,
        *,
        timeout_s: float,
        headers: tuple[tuple[str, str], ...] = (),
    ) -> JsonHttpResponse:
        self._bind_loop()
        timeout = self._validate_timeout(timeout_s, "model endpoint HTTP timeout")
        per_request = self._validate_headers(headers)
        if type(body) is not bytes:
            raise TypeError("model endpoint HTTP body must be pre-encoded bytes")
        if not body:
            raise ValueError("model endpoint HTTP body must not be empty")
        encoded = body
        with self._state_lock:
            self._requests_started += 1

        try:
            async with asyncio.timeout(timeout):
                async with self._client.stream(
                    "POST",
                    url,
                    content=encoded,
                    headers=self._request_headers(
                        per_request,
                        accept="application/json",
                    ),
                    timeout=self._request_timeout(timeout_s=timeout),
                ) as response:
                    raw = await self._read_bounded_raw(
                        response,
                        request_body=encoded,
                    )
                    version = response.http_version
                    response_headers = self._response_headers(response)
                    status = response.status_code
        except ModelEndpointError:
            with self._state_lock:
                self._requests_failed += 1
            raise
        except TimeoutError as exc:
            with self._state_lock:
                self._requests_failed += 1
            raise ModelEndpointError(
                "model endpoint HTTP total request timeout",
                request_body=encoded,
                failure_kind="timeout",
                retryable=True,
                affects_replica_health=True,
                transport_digest=self._transport_digest,
            ) from exc
        except httpx.HTTPError as exc:
            with self._state_lock:
                self._requests_failed += 1
            raise self._translate_httpx_error(
                exc,
                request_body=encoded,
            ) from exc

        self._record_http_version(version)
        try:
            parsed_body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            with self._state_lock:
                self._requests_failed += 1
            raise ModelEndpointError(
                "model endpoint HTTP response is not valid JSON",
                request_body=encoded,
                response_body=raw,
                status_code=status,
                response_headers=response_headers,
                failure_kind="invalid_request",
                retryable=False,
                affects_replica_health=False,
                http_version=version,
                transport_digest=self._transport_digest,
            ) from exc

        with self._state_lock:
            self._requests_completed += 1
        return JsonHttpResponse(
            status,
            parsed_body,
            raw_body=raw,
            request_body=encoded,
            response_headers=response_headers,
            http_version=version,
            transport_digest=self._transport_digest,
        )

    async def post_sse(
        self,
        url: str,
        body: bytes,
        *,
        timeout_s: float,
        idle_timeout_s: float,
        on_event: Callable[[RawServerSentEvent], None],
        headers: tuple[tuple[str, str], ...] = (),
    ) -> SseHttpResponse:
        self._bind_loop()
        total_timeout = self._validate_timeout(
            timeout_s,
            "model endpoint SSE total timeout",
        )
        idle_timeout = self._validate_timeout(
            idle_timeout_s,
            "model endpoint SSE idle timeout",
        )
        if not callable(on_event):
            raise TypeError("model endpoint SSE on_event must be callable")
        per_request = self._validate_headers(headers)
        if type(body) is not bytes:
            raise TypeError("model endpoint SSE body must be pre-encoded bytes")
        if not body:
            raise ValueError("model endpoint SSE body must not be empty")
        encoded = body
        decoder = ServerSentEventDecoder(
            max_event_bytes=self._max_sse_event_bytes
        )
        raw_parts: list[bytes] = []
        total = 0
        event_count = 0
        with self._state_lock:
            self._streams_started += 1

        def consume(chunk: bytes) -> None:
            nonlocal total, event_count
            total += len(chunk)
            if total > self._max_response_bytes:
                raise ModelEndpointError(
                    "model endpoint SSE response exceeds configured limit",
                    request_body=encoded,
                    response_body=b"".join(raw_parts),
                    failure_kind="invalid_request",
                    retryable=False,
                    affects_replica_health=False,
                    transport_digest=self._transport_digest,
                )
            raw_parts.append(chunk)
            for event in decoder.feed(chunk):
                event_count += 1
                # Synchronous delivery deliberately applies backpressure rather
                # than accumulating an unbounded event queue.
                on_event(event)

        try:
            async with asyncio.timeout(total_timeout):
                async with self._client.stream(
                    "POST",
                    url,
                    content=encoded,
                    headers=self._request_headers(
                        per_request,
                        accept="text/event-stream",
                    ),
                    timeout=self._request_timeout(
                        timeout_s=total_timeout,
                        read_timeout_s=idle_timeout,
                    ),
                ) as response:
                    status = response.status_code
                    version = response.http_version
                    response_headers = self._response_headers(response)
                    if not 200 <= status < 300:
                        raw = await self._read_bounded_raw(
                            response,
                            request_body=encoded,
                        )
                        self._record_http_version(version)
                        with self._state_lock:
                            self._streams_completed += 1
                        return SseHttpResponse(
                            status_code=status,
                            response_headers=response_headers,
                            request_body=encoded,
                            raw_body=raw,
                            event_count=0,
                            http_version=version,
                            transport_digest=self._transport_digest,
                        )

                    content_type = response.headers.get(
                        "content-type", ""
                    ).lower()
                    if "text/event-stream" not in content_type:
                        raise ModelEndpointError(
                            "model endpoint streaming response is not text/event-stream",
                            request_body=encoded,
                            failure_kind="invalid_request",
                            retryable=False,
                            affects_replica_health=False,
                            http_version=version,
                            transport_digest=self._transport_digest,
                        )

                    async for chunk in response.aiter_raw():
                        consume(chunk)
                    for event in decoder.finish():
                        event_count += 1
                        on_event(event)
        except ModelEndpointError:
            with self._state_lock:
                self._streams_failed += 1
            raise
        except TimeoutError as exc:
            with self._state_lock:
                self._streams_failed += 1
            raise ModelEndpointError(
                "model endpoint SSE total request timeout",
                request_body=encoded,
                response_body=b"".join(raw_parts),
                failure_kind="timeout",
                retryable=True,
                affects_replica_health=True,
                transport_digest=self._transport_digest,
            ) from exc
        except httpx.HTTPError as exc:
            with self._state_lock:
                self._streams_failed += 1
            raise self._translate_httpx_error(
                exc,
                request_body=encoded,
                response_body=b"".join(raw_parts),
            ) from exc

        raw = b"".join(raw_parts)
        self._record_http_version(version)
        with self._state_lock:
            self._streams_completed += 1
        return SseHttpResponse(
            status_code=status,
            response_headers=response_headers,
            request_body=encoded,
            raw_body=raw,
            event_count=event_count,
            http_version=version,
            transport_digest=self._transport_digest,
        )


class PooledModelHttpTransportOwner:
    """Retryable synchronous lifecycle owner for one shared async HTTP transport."""

    def __init__(
        self,
        transport: PooledModelHttpTransport,
        task_group: TaskGroupPort,
        *,
        close_timeout_s: float = 30.0,
    ) -> None:
        if not isinstance(transport, PooledModelHttpTransport):
            raise TypeError("pooled model HTTP owner requires PooledModelHttpTransport")
        if not callable(getattr(task_group, "submit", None)):
            raise TypeError("pooled model HTTP owner requires task-group submit authority")
        if (
            isinstance(close_timeout_s, bool)
            or not isinstance(close_timeout_s, (int, float))
            or not math.isfinite(float(close_timeout_s))
            or float(close_timeout_s) <= 0
        ):
            raise ValueError("pooled model HTTP owner close timeout must be finite and positive")
        self.transport = transport
        self._task_group = task_group
        self._close_timeout_s = float(close_timeout_s)
        self._lock = Lock()
        self._closed = False
        self._close_sequence = 0

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    async def _aclose(self, context) -> None:
        context.checkpoint()
        await self.transport.aclose()
        context.checkpoint()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._close_sequence += 1
            sequence = self._close_sequence
            deadline = Deadline.after(self._close_timeout_s)
            handle = self._task_group.submit(
                ExecutionSpec(
                    task_id=f"shared-model-http-transport-close:{sequence}",
                    lane_kind=ExecutionLaneKind.ASYNC_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                self._aclose,
                deadline=deadline,
            )
            handle.result(timeout=max(0.001, deadline.remaining_seconds))
            self._closed = True


__all__ = [
    "PooledModelHttpTransport",
    "PooledModelHttpTransportOwner",
    "PooledModelHttpTransportSnapshot",
]
