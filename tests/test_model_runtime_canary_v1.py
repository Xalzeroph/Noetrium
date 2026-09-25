from __future__ import annotations

from collections.abc import Mapping

import time

import pytest

from noetrium_platform.capabilities.model.serving.api import (
    DeploymentPlacement,
    QualificationCertificate,
    QualifiedDeploymentManifest,
    ResourceEnvelope,
    RuntimeCanaryContract,
    RuntimeCanaryProbe,
    ServiceHeartbeat,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointResponse,
    ModelEndpointRoute,
)
from noetrium_platform.capabilities.model.serving.runtime import run_runtime_canary
from noetrium_platform.capabilities.model.stack.api import ModelArtifactClosure, ModelStackSpec, RuntimeBuildIdentity
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity, canonical_digest


def _digest(seed: str) -> str:
    return (seed * 64)[:64]


def _deployment() -> QualifiedDeploymentManifest:
    identity = ImmutableModelIdentity(
        "planner-model", "repo/model", "revision", "vllm", "0.1",
        "bfloat16", None, 8192,
    )
    stack = ModelStackSpec(
        identity,
        ModelArtifactClosure(_digest("a"), _digest("b"), _digest("c")),
        RuntimeBuildIdentity(
            _digest("d"), _digest("e"), _digest("f"),
            "cuda", "nccl", "torch", _digest("1"),
        ),
        1, 1, 1, 1, None, None, None, None, "fcfs",
    )
    certificate = QualificationCertificate(
        stack.digest(), _digest("2"), ("planner",),
        ResourceEnvelope(1, 1, 1, 1.0, 1.0, 1.0),
        _digest("3"),
    )
    return QualifiedDeploymentManifest(
        "deployment-1", stack, certificate,
        DeploymentPlacement(("GPU-1",)), _digest("3"),
    )


def _route(deployment: QualifiedDeploymentManifest) -> ModelEndpointRoute:
    return ModelEndpointRoute(
        deployment.deployment_id,
        deployment.digest(),
        "http://127.0.0.1:30000",
        timeout_s=10.0,
    )


def _heartbeat(deployment: QualifiedDeploymentManifest, *, marker: str = "start-a") -> ServiceHeartbeat:
    return ServiceHeartbeat(
        deployment.deployment_id,
        deployment.stack.digest(),
        101,
        marker,
        _digest('4'),
        True,
        deployment.certificate.digest(),
        time.time() - 0.1,
    )


class _Endpoint:
    def __init__(self, route: ModelEndpointRoute, *, text: str = '{"ok": true}', finish_reason: str | None = 'stop') -> None:
        self.route = route
        self.text = text
        self.finish_reason = finish_reason
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return ModelEndpointResponse(
            request_id=request.request.request_id,
            deployment_id=request.deployment_id,
            text=self.text,
            finish_reason=self.finish_reason,
            input_tokens=4,
            output_tokens=2,
        )


def _probe() -> RuntimeCanaryProbe:
    return RuntimeCanaryProbe(
        'planner-json',
        'planner',
        _digest('5'),
        {'model': 'planner-model', 'messages': [{'role': 'user', 'content': 'return JSON'}]},
        RuntimeCanaryContract('json-ok', True, ('ok',), ('stop',)),
    )


def test_runtime_canary_binds_request_response_and_process_generation() -> None:
    deployment = _deployment()
    heartbeat = _heartbeat(deployment)
    endpoint = _Endpoint(_route(deployment))
    evidence = run_runtime_canary(
        endpoint,
        deployment,
        _route(deployment),
        heartbeat,
        _probe(),
        max_heartbeat_age_seconds=60.0, now=time.time(),
    )

    assert evidence.passed is True
    assert evidence.deployment_generation == deployment.digest()
    assert evidence.process_pid == heartbeat.pid
    assert evidence.process_start_marker == heartbeat.process_start_marker
    assert evidence.argv_digest == heartbeat.argv_digest
    assert len(evidence.request_digest) == 64
    assert evidence.probe_digest == _probe().digest()
    assert len(evidence.response_digest) == 64
    assert len(evidence.evidence_digest) == 64
    assert len(endpoint.requests) == 1
    assert endpoint.requests[0].request.role == 'planner'
    assert isinstance(endpoint.requests[0].body, Mapping)
    with pytest.raises(TypeError):
        endpoint.requests[0].body["model"] = "tampered"
    assert isinstance(endpoint.requests[0].body['messages'], tuple)
    with pytest.raises((TypeError, AttributeError)):
        endpoint.requests[0].body['messages'].append({'role': 'user', 'content': 'tampered'})


def test_runtime_canary_contract_failure_is_explicit_failed_evidence() -> None:
    deployment = _deployment()
    evidence = run_runtime_canary(
        _Endpoint(_route(deployment), text='not-json'),
        deployment,
        _route(deployment),
        _heartbeat(deployment),
        _probe(),
        max_heartbeat_age_seconds=60.0, now=time.time(),
    )
    assert evidence.passed is False


def test_runtime_canary_rejects_route_and_heartbeat_generation_drift() -> None:
    deployment = _deployment()
    route = _route(deployment)
    heartbeat = _heartbeat(deployment)
    with pytest.raises(ValueError, match='route'):
        run_runtime_canary(
            _Endpoint(route), deployment,
            ModelEndpointRoute(route.deployment_id, _digest('9'), route.base_url),
            heartbeat, _probe(), max_heartbeat_age_seconds=60.0, now=time.time(),
        )

    other = ServiceHeartbeat(
        heartbeat.deployment_id,
        heartbeat.stack_digest,
        heartbeat.pid,
        'start-other',
        heartbeat.argv_digest,
        heartbeat.ready,
        heartbeat.qualification_digest,
        heartbeat.timestamp,
    )
    first = run_runtime_canary(_Endpoint(route), deployment, route, heartbeat, _probe(), max_heartbeat_age_seconds=60.0, now=time.time())
    second = run_runtime_canary(_Endpoint(route), deployment, route, other, _probe(), max_heartbeat_age_seconds=60.0, now=time.time())
    assert first.evidence_digest != second.evidence_digest


def test_runtime_canary_rejects_stale_heartbeat_before_endpoint_call() -> None:
    deployment = _deployment()
    heartbeat = _heartbeat(deployment)
    stale = ServiceHeartbeat(
        heartbeat.deployment_id, heartbeat.stack_digest, heartbeat.pid,
        heartbeat.process_start_marker, heartbeat.argv_digest, heartbeat.ready,
        heartbeat.qualification_digest, time.time() - 120.0,
    )
    endpoint = _Endpoint(_route(deployment))
    with pytest.raises(ValueError, match="stale"):
        run_runtime_canary(
            endpoint, deployment, _route(deployment), stale, _probe(),
            max_heartbeat_age_seconds=60.0, now=time.time(),
        )
    assert endpoint.requests == []


def test_runtime_canary_exact_json_digest_rejects_semantic_drift() -> None:
    deployment = _deployment()
    expected = canonical_digest({"status": "ok"})
    probe = RuntimeCanaryProbe(
        "planner-semantic",
        "planner",
        _digest("6"),
        {"model": "planner-model", "messages": [], "chat_template_kwargs": {"enable_thinking": False}},
        RuntimeCanaryContract("exact-ok", True, ("status",), ("stop",), expected),
    )
    passed = run_runtime_canary(
        _Endpoint(_route(deployment), text='{"status":"ok"}'), deployment, _route(deployment),
        _heartbeat(deployment), probe, max_heartbeat_age_seconds=30.0, now=time.time(),
    )
    drifted = run_runtime_canary(
        _Endpoint(_route(deployment), text='{"status":"almost"}'), deployment, _route(deployment),
        _heartbeat(deployment), probe, max_heartbeat_age_seconds=30.0, now=time.time(),
    )
    assert passed.passed is True
    assert drifted.passed is False

def test_runtime_canary_probe_deep_freezes_request_identity() -> None:
    request = {
        "model": "planner-model",
        "messages": [{"role": "user", "content": "before"}],
        "chat_template_kwargs": {"enable_thinking": False},
    }
    probe = RuntimeCanaryProbe(
        "immutable-request", "planner", _digest("7"), request,
        RuntimeCanaryContract("non-empty"),
    )
    original_digest = probe.digest()
    request["messages"][0]["content"] = "after"
    request["chat_template_kwargs"]["enable_thinking"] = True
    assert probe.digest() == original_digest
    assert probe.request_body["messages"][0]["content"] == "before"
    with pytest.raises(TypeError):
        probe.request_body["model"] = "mutated"
    with pytest.raises(TypeError):
        probe.request_body["messages"][0]["content"] = "mutated"


def test_runtime_canary_rejects_endpoint_route_substitution() -> None:
    deployment = _deployment()
    authority_route = _route(deployment)
    substituted = ModelEndpointRoute(
        authority_route.deployment_id, authority_route.deployment_generation,
        "http://127.0.0.1:39999", authority_route.completion_path, authority_route.timeout_s,
    )
    endpoint = _Endpoint(substituted)
    with pytest.raises(ValueError, match="route authority drift"):
        run_runtime_canary(
            endpoint, deployment, authority_route, _heartbeat(deployment), _probe(),
            max_heartbeat_age_seconds=60.0, now=time.time(),
        )
    assert endpoint.requests == []
