from __future__ import annotations

import asyncio
import threading
import time
from uuid import uuid4

import pytest

from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.capabilities.model.serving.api import ResourceEnvelope
from noetrium_platform.capabilities.model.serving.endpoint import (
    JsonHttpResponse,
    ModelEndpointError,
    ModelEndpointRequest,
    ModelEndpointResponse,
    ModelEndpointRoute,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import QualifiedModelEndpointBinding
from noetrium_platform.capabilities.model.serving.endpoint.composition import build_openai_compatible_qualified_endpoint
from noetrium_platform.capabilities.model.serving.endpoint.providers import OpenAICompatibleModelEndpoint
from noetrium_platform.capabilities.model.serving.runtime import (
    ModelAdmissionController,
    ModelAdmissionRegistry,
)
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity


def _envelope(request_id: str = "request") -> ModelRequestEnvelope:
    return ModelRequestEnvelope(
        schema_version="model-request.v1", request_id=request_id,
        context=ExecutionContext("run", "trace", "span"), role="planner",
        model=ImmutableModelIdentity("planner", "qwen", "rev", "sglang", "1", "bfloat16", None, 8192),
        prompt_generation_id="prompt-gen", prompt_id="planner.prompt", prompt_digest="d" * 64,
        request_body=ArtifactBlobRef("f" * 64, 2, "application/json"),
    )


def _request(request_id: str = "request") -> ModelEndpointRequest:
    return ModelEndpointRequest(
        request=_envelope(request_id), deployment_id="deployment", deployment_generation="a" * 64,
        body={"model": "qwen", "messages": []},
    )


class _DelayedCancellationTransport:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.cancel_seen = threading.Event()
        self.finished = threading.Event()

    async def post_json(
        self,
        url: str,
        body: dict[str, object],
        *,
        timeout_s: float,
    ) -> JsonHttpResponse:
        del url, body, timeout_s
        self.started.set()
        try:
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            self.cancel_seen.set()
            await asyncio.sleep(0.10)
            self.finished.set()
            return JsonHttpResponse(200, {"choices": [{"text": "late"}]})
        raise AssertionError("transport was expected to be cancelled")


class _StaticTransport:
    def __init__(self, body: object) -> None:
        self.body = body

    async def post_json(
        self,
        url: str,
        body: dict[str, object],
        *,
        timeout_s: float,
    ) -> JsonHttpResponse:
        del url, body, timeout_s
        return JsonHttpResponse(200, self.body)


def _endpoint(runtime, transport, admission, *, timeout_s: float = 1.0):
    group = runtime.open_task_group(f"model-endpoint-admission:{uuid4().hex}")
    return OpenAICompatibleModelEndpoint(
        route=ModelEndpointRoute(
            "deployment",
            "a" * 64,
            "http://127.0.0.1:30000",
            timeout_s=timeout_s,
        ),
        transport=transport,
        task_group=group,
        admission=admission,
    )


def test_registry_reuses_exact_deployment_capacity_authority() -> None:
    registry = ModelAdmissionRegistry()
    first = registry.controller_for(
        deployment_id="deployment", deployment_generation="a" * 64, qualified_capacity=2
    )
    second = registry.controller_for(
        deployment_id="deployment", deployment_generation="a" * 64, qualified_capacity=2
    )
    assert first is second

    with pytest.raises(ValueError, match="capacity drift"):
        registry.controller_for(
            deployment_id="deployment",
            deployment_generation="a" * 64,
            qualified_capacity=3,
        )


def test_timeout_keeps_lease_until_async_transport_physically_finishes() -> None:
    runtime = build_concurrency_runtime()
    admission = ModelAdmissionController(1)
    transport = _DelayedCancellationTransport()
    endpoint = _endpoint(runtime, transport, admission, timeout_s=0.05)
    try:
        with pytest.raises(ModelEndpointError, match="TimeoutError|deadline"):
            endpoint.complete(_request())
        assert transport.started.is_set()
        assert transport.cancel_seen.wait(1.0)
        assert admission.snapshot().active == 1
        assert transport.finished.wait(1.0)
        deadline = time.monotonic() + 1.0
        while admission.snapshot().active and time.monotonic() < deadline:
            time.sleep(0.01)
        assert admission.snapshot().active == 0
    finally:
        runtime.close()


def test_boolean_token_counts_are_rejected() -> None:
    runtime = build_concurrency_runtime()
    admission = ModelAdmissionController(1)
    transport = _StaticTransport(
        {
            "choices": [{"text": "ok"}],
            "usage": {"prompt_tokens": True, "completion_tokens": 1},
        }
    )
    endpoint = _endpoint(runtime, transport, admission)
    try:
        with pytest.raises(ModelEndpointError, match="prompt_tokens"):
            endpoint.complete(_request())
        assert admission.snapshot().active == 0
    finally:
        runtime.close()


def test_registry_close_closes_shared_controller() -> None:
    registry = ModelAdmissionRegistry()
    controller = registry.controller_for(
        deployment_id="deployment", deployment_generation="a" * 64, qualified_capacity=1
    )
    registry.close()
    assert registry.closed
    assert controller.closed
    with pytest.raises(Exception, match="closed"):
        controller.acquire(timeout_seconds=0.0)


class _ConcurrentTransport:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    async def post_json(
        self,
        url: str,
        body: dict[str, object],
        *,
        timeout_s: float,
    ) -> JsonHttpResponse:
        del url, body, timeout_s
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.05)
            return JsonHttpResponse(200, {"choices": [{"text": "ok"}]})
        finally:
            with self._lock:
                self.active -= 1


def test_two_endpoints_share_qualified_deployment_capacity() -> None:
    runtime = build_concurrency_runtime()
    registry = ModelAdmissionRegistry()
    controller = registry.controller_for(
        deployment_id="deployment",
        deployment_generation="a" * 64,
        qualified_capacity=1,
    )
    transport = _ConcurrentTransport()
    first = _endpoint(runtime, transport, controller)
    second = _endpoint(runtime, transport, controller)
    results: list[str] = []
    failures: list[BaseException] = []

    def invoke(endpoint, request_id: str) -> None:
        try:
            results.append(endpoint.complete(_request(request_id)).text)
        except BaseException as exc:
            failures.append(exc)

    threads = [
        threading.Thread(target=invoke, args=(first, "one")),
        threading.Thread(target=invoke, args=(second, "two")),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2.0)
        assert all(not thread.is_alive() for thread in threads)
        assert failures == []
        assert sorted(results) == ["ok", "ok"]
        assert transport.max_active == 1
        assert controller.snapshot().active == 0
    finally:
        runtime.close()


class _RecordingRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.controller: ModelAdmissionController | None = None

    def controller_for(
        self,
        *,
        deployment_id: str,
        deployment_generation: str,
        qualified_capacity: int,
    ) -> ModelAdmissionController:
        self.calls.append((deployment_id, deployment_generation, qualified_capacity))
        self.controller = ModelAdmissionController(qualified_capacity)
        return self.controller

    def close(self) -> None:
        if self.controller is not None:
            self.controller.close()


def test_qualified_builder_uses_frozen_binding_concurrency() -> None:
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group(f"qualified-builder:{uuid4().hex}")
    registry = _RecordingRegistry()
    identity = ImmutableModelIdentity(
        "model", "repo/model", "rev", "engine", "1", "bfloat16", None, 4096
    )
    binding = QualifiedModelEndpointBinding(
        role="planner",
        deployment_id="deployment",
        deployment_generation="a" * 64,
        base_url="http://127.0.0.1:30000",
        model=identity,
        model_stack_digest="b" * 64,
        qualification_certificate_digest="c" * 64,
        runtime_qualification_digest="d" * 64,
        host_identity_digest="e" * 64,
        prompt_generation="prompt-v1",
        max_admitted_concurrency=3,
        runtime_canary_evidence_digests=("f" * 64,),
    )
    try:
        endpoint = build_openai_compatible_qualified_endpoint(
            binding,
            task_group=group,
            admission_registry=registry,
        )
        assert isinstance(endpoint, OpenAICompatibleModelEndpoint)
        assert registry.calls == [("deployment", "a" * 64, 3)]
        assert registry.controller is not None
        assert registry.controller.capacity == 3
    finally:
        registry.close()
        runtime.close()


def test_capacity_and_token_contracts_reject_boolean_integers() -> None:
    with pytest.raises(ValueError, match="qualified capacity"):
        ModelAdmissionController(True)
    with pytest.raises(ValueError, match="qualified concurrency"):
        ResourceEnvelope(1, 1, True, 1.0, 1.0, 1.0)
    with pytest.raises(ValueError, match="input_tokens"):
        ModelEndpointResponse(
            request_id="request",
            deployment_id="deployment",
            text="ok",
            input_tokens=True,
        )
