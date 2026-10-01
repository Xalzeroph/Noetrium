from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from .contracts import JsonHttpResponse, ModelEndpointRequest, ModelEndpointResponse, ModelEndpointRoute
from .streaming import ModelStreamEvent, RawServerSentEvent, SseHttpResponse


@runtime_checkable
class AsyncJsonHttpTransportPort(Protocol):
    """True async HTTP transport seam owned by platform.concurrency."""

    async def post_json(
        self,
        url: str,
        body: bytes,
        *,
        timeout_s: float,
        headers: tuple[tuple[str, str], ...] = (),
    ) -> JsonHttpResponse: ...




@runtime_checkable
class ModelJsonHttpClientPort(Protocol):
    """Synchronous JSON request seam backed by owned structured async I/O."""

    def post_json(
        self,
        url: str,
        body: bytes,
        *,
        timeout_s: float,
        headers: tuple[tuple[str, str], ...] = (),
    ) -> JsonHttpResponse: ...

    def close(self) -> None: ...


@runtime_checkable
class AsyncTextHttpTransportPort(Protocol):
    """Read-only text HTTP seam sharing the model transport owner."""

    async def get_text(
        self,
        url: str,
        *,
        timeout_s: float,
        headers: tuple[tuple[str, str], ...] = (),
    ) -> str: ...


@runtime_checkable
class AsyncJsonSseTransportPort(Protocol):
    """Streaming HTTP transport that emits exact SSE frames incrementally."""

    async def post_sse(
        self,
        url: str,
        body: bytes,
        *,
        timeout_s: float,
        idle_timeout_s: float,
        on_event: Callable[[RawServerSentEvent], None],
        headers: tuple[tuple[str, str], ...] = (),
    ) -> SseHttpResponse: ...


class ModelEndpointPort(Protocol):
    """Synchronous project-facing inference seam backed by owned async I/O."""

    @property
    def route(self) -> ModelEndpointRoute: ...

    def complete(self, request: ModelEndpointRequest) -> ModelEndpointResponse: ...

    def stream(
        self,
        request: ModelEndpointRequest,
        on_event: Callable[[ModelStreamEvent], None],
        *,
        stream_idle_timeout_s: float = 30.0,
    ) -> ModelEndpointResponse: ...


class ModelEndpointFactoryPort(Protocol):
    def create(self, route: ModelEndpointRoute) -> ModelEndpointPort: ...


__all__ = [
    "AsyncJsonHttpTransportPort",
    "AsyncJsonSseTransportPort",
    "AsyncTextHttpTransportPort",
    "ModelEndpointFactoryPort",
    "ModelEndpointPort",
    "ModelJsonHttpClientPort",
]
