"""Raw HTTPcore disconnects must enter the shared replica retry authority."""
from __future__ import annotations

import asyncio

import httpcore

from noetrium_platform.capabilities.model.serving.endpoint.providers.http_pool import (
    PooledModelHttpTransport,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import ModelEndpointError


class _ReadErrorClient:
    def stream(self, *args, **kwargs):
        class _Broken:
            async def __aenter__(self):
                raise httpcore.ReadError("peer closed stream")
            async def __aexit__(self, *_):
                return False
        return _Broken()

    async def aclose(self):
        return None


def test_raw_httpcore_read_error_is_retryable_model_endpoint_transport_error():
    async def check():
        transport = PooledModelHttpTransport()
        original = transport._client
        transport._client = _ReadErrorClient()
        try:
            failure = None
            try:
                await transport.post_json(
                    "http://127.0.0.1:4000/v1/chat/completions",
                    b'{"messages":[]}',
                    timeout_s=3,
                )
            except ModelEndpointError as exc:
                failure = exc
            assert failure is not None, "raw HTTPcore read error escaped the model endpoint boundary"
            assert failure.failure_kind == "transient"
            assert failure.retryable is True
            assert failure.affects_replica_health is True
            assert type(failure.__cause__) is httpcore.ReadError
            assert transport.snapshot().requests_failed == 1
        finally:
            transport._client = original
            await transport.aclose()

    asyncio.run(check())
