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


def test_runtime_canary_contract_rejects_unproven_capability_labels() -> None:
    with pytest.raises(ValueError, match="reasoning content-block proof"):
        RuntimeCanaryContract(
            "bad-reasoning",
            verified_capabilities=("reasoning",),
        )
    with pytest.raises(ValueError, match="tool-call proof"):
        RuntimeCanaryContract(
            "bad-tools",
            verified_capabilities=("tools",),
        )
    with pytest.raises(ValueError, match="JSON object proof"):
        RuntimeCanaryContract(
            "bad-structured",
            verified_capabilities=("structured_output",),
        )
    with pytest.raises(ValueError, match="completed stream-event proof"):
        RuntimeCanaryContract(
            "bad-stream",
            verified_capabilities=("streaming",),
        )


def test_runtime_canary_reasoning_requires_canonical_reasoning_block() -> None:
    deployment=_deployment()
    route=_route(deployment)
    contract=RuntimeCanaryContract(
        "reasoning-proof",
        verified_capabilities=("reasoning",),
        required_content_block_kinds=("reasoning",),
    )
    probe=RuntimeCanaryProbe(
        "reasoning-probe",
        "planner",
        _digest("8"),
        {"model":"planner-model","messages":[{"role":"user","content":"reason"}]},
        contract,
    )

    class Endpoint(_Endpoint):
        def __init__(self, route, with_reasoning):
            super().__init__(route,text="answer",finish_reason="stop")
            self.with_reasoning=with_reasoning
        def complete(self, request):
            self.requests.append(request)
            blocks=(
                {
                    "kind":"reasoning",
                    "provider_id":"vllm",
                    "provider_payload":{"type":"reasoning"},
                    "text":"reason",
                },
                {
                    "kind":"text",
                    "provider_id":"vllm",
                    "provider_payload":{"type":"text"},
                    "text":"answer",
                },
            ) if self.with_reasoning else (
                {
                    "kind":"text",
                    "provider_id":"vllm",
                    "provider_payload":{"type":"text"},
                    "text":"<think>reason</think> answer",
                },
            )
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="answer",
                content_blocks=blocks,
                finish_reason="stop",
            )

    proved=run_runtime_canary(
        Endpoint(route,True),deployment,route,_heartbeat(deployment),probe,
        max_heartbeat_age_seconds=60.0,now=time.time(),
    )
    text_only=run_runtime_canary(
        Endpoint(route,False),deployment,route,_heartbeat(deployment),probe,
        max_heartbeat_age_seconds=60.0,now=time.time(),
    )
    assert proved.passed is True
    assert proved.verified_capabilities==("generation","reasoning")
    assert text_only.passed is False
    assert text_only.verified_capabilities==()


def test_runtime_canary_tool_capability_requires_expected_tool_call() -> None:
    deployment=_deployment()
    route=_route(deployment)
    probe=RuntimeCanaryProbe(
        "tool-probe",
        "planner",
        _digest("9"),
        {
            "model":"planner-model",
            "messages":[{"role":"user","content":"call probe_tool"}],
            "tools":[{
                "type":"function",
                "function":{
                    "name":"probe_tool",
                    "parameters":{"type":"object","properties":{}},
                },
            }],
        },
        RuntimeCanaryContract(
            "tool-proof",
            verified_capabilities=("tools",),
            require_non_empty_text=False,
            required_tool_names=("probe_tool",),
            minimum_tool_calls=1,
        ),
    )

    class Endpoint(_Endpoint):
        def complete(self, request):
            self.requests.append(request)
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="",
                tool_calls=({
                    "id":"call-1",
                    "type":"function",
                    "function":{"name":"probe_tool","arguments":{}},
                },),
                finish_reason="tool_calls",
            )

    evidence=run_runtime_canary(
        Endpoint(route),deployment,route,_heartbeat(deployment),probe,
        max_heartbeat_age_seconds=60.0,now=time.time(),
    )
    assert evidence.passed is True
    assert evidence.verified_capabilities==("generation","tools")


def test_runtime_canary_streaming_requires_real_stream_events_and_binds_digest() -> None:
    from noetrium_platform.capabilities.model.serving.endpoint.api import (
        ModelStreamEvent,
        ModelStreamEventKind,
    )
    deployment=_deployment()
    route=_route(deployment)
    contract=RuntimeCanaryContract(
        "stream-proof",
        verified_capabilities=("streaming",),
        required_stream_event_kinds=("text_delta","completed"),
    )
    with pytest.raises(ValueError,match="stream execution mode"):
        RuntimeCanaryProbe(
            "stream-bad","planner",_digest("a"),
            {"model":"planner-model","messages":[{"role":"user","content":"x"}]},
            contract,
        )
    probe=RuntimeCanaryProbe(
        "stream-good",
        "planner",
        _digest("b"),
        {"model":"planner-model","messages":[{"role":"user","content":"x"}]},
        contract,
        execution_mode="stream",
    )

    class Endpoint(_Endpoint):
        def stream(self, request, on_event):
            self.requests.append(request)
            on_event(ModelStreamEvent(
                kind=ModelStreamEventKind.TEXT_DELTA,
                sequence=1,
                provider_event_type="response.output_text.delta",
                provider_id="vllm",
                text_delta="ok",
            ))
            on_event(ModelStreamEvent(
                kind=ModelStreamEventKind.COMPLETED,
                sequence=2,
                provider_event_type="response.completed",
                provider_id="vllm",
                content={"response":{"status":"completed"}},
                terminal=True,
            ))
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="ok",
                finish_reason="stop",
            )

    evidence=run_runtime_canary(
        Endpoint(route),deployment,route,_heartbeat(deployment),probe,
        max_heartbeat_age_seconds=60.0,now=time.time(),
    )
    assert evidence.passed is True
    assert evidence.execution_mode=="stream"
    assert evidence.verified_capabilities==("generation","streaming")
    assert evidence.stream_digest is not None
    assert len(evidence.stream_digest)==64


def test_runtime_canary_responses_capability_requires_responses_route() -> None:
    deployment=_deployment()
    chat_route=_route(deployment)
    probe=RuntimeCanaryProbe(
        "responses-probe",
        "planner",
        _digest("c"),
        {"model":"planner-model","messages":[{"role":"user","content":"x"}]},
        RuntimeCanaryContract(
            "responses-proof",
            verified_capabilities=("responses",),
        ),
    )
    chat=run_runtime_canary(
        _Endpoint(chat_route,text="ok"),
        deployment,
        chat_route,
        _heartbeat(deployment),
        probe,
        max_heartbeat_age_seconds=60.0,
        now=time.time(),
    )
    responses_route=ModelEndpointRoute(
        chat_route.deployment_id,
        chat_route.deployment_generation,
        chat_route.base_url,
        completion_path="/v1/responses",
        timeout_s=chat_route.timeout_s,
    )
    responses=run_runtime_canary(
        _Endpoint(responses_route,text="ok"),
        deployment,
        responses_route,
        _heartbeat(deployment),
        probe,
        max_heartbeat_age_seconds=60.0,
        now=time.time(),
    )
    assert chat.passed is False
    assert responses.passed is True
    assert responses.verified_capabilities==("generation","responses")
