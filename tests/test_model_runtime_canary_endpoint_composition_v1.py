from __future__ import annotations

import pytest

from noetrium_platform.capabilities.model.serving.endpoint.api import JsonHttpResponse, ModelEndpointRoute
from noetrium_platform.capabilities.model.serving.endpoint.composition import (
    build_openai_compatible_runtime_canary_endpoint,
)
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionRegistry
from tests.test_model_runtime_canary_v1 import _deployment, _digest, _route


class _Transport:
    async def post_json(self, url, body, *, timeout_s):
        del url, body, timeout_s
        return JsonHttpResponse(200, {
            "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })


def test_preclosure_canary_endpoints_share_qualified_admission_authority() -> None:
    deployment = _deployment()
    route = _route(deployment)
    registry = ModelAdmissionRegistry()
    transport = _Transport()

    first = build_openai_compatible_runtime_canary_endpoint(
        deployment, route, task_group=object(), admission_registry=registry, transport=transport,
    )
    second = build_openai_compatible_runtime_canary_endpoint(
        deployment, route, task_group=object(), admission_registry=registry, transport=transport,
    )

    assert first.route == route
    assert second.route == route
    assert first._admission is second._admission
    assert first._admission.snapshot().capacity == (
        deployment.certificate.resource_envelope.max_qualified_concurrency
    )
    registry.close()


def test_preclosure_canary_endpoint_rejects_route_generation_drift() -> None:
    deployment = _deployment()
    route = _route(deployment)
    drifted = ModelEndpointRoute(
        route.deployment_id,
        _digest("9"),
        route.base_url,
        route.completion_path,
        route.timeout_s,
    )
    with pytest.raises(ValueError, match="generation drift"):
        build_openai_compatible_runtime_canary_endpoint(
            deployment,
            drifted,
            task_group=object(),
            admission_registry=ModelAdmissionRegistry(),
            transport=_Transport(),
        )
