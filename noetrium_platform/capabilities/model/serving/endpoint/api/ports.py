from __future__ import annotations

from typing import Protocol
from noetrium_platform.foundation.kernel.kernel import JsonInput

from .contracts import JsonHttpResponse, ModelEndpointRequest, ModelEndpointResponse, ModelEndpointRoute


class AsyncJsonHttpTransportPort(Protocol):
    """True async HTTP transport seam owned by platform.concurrency."""

    async def post_json(
        self,
        url: str,
        body: dict[str, JsonInput],
        *,
        timeout_s: float,
    ) -> JsonHttpResponse: ...


class ModelEndpointPort(Protocol):
    """Synchronous project-facing inference seam backed by owned async I/O."""

    @property
    def route(self) -> ModelEndpointRoute: ...

    def complete(self, request: ModelEndpointRequest) -> ModelEndpointResponse: ...


class ModelEndpointFactoryPort(Protocol):
    def create(self, route: ModelEndpointRoute) -> ModelEndpointPort: ...


__all__ = ["AsyncJsonHttpTransportPort", "ModelEndpointFactoryPort", "ModelEndpointPort"]
