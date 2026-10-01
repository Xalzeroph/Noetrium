from __future__ import annotations

import json
from uuid import uuid4

import pytest

from noetrium_platform.capabilities.model.request.api import (
    ModelOperationEnvelope,
    ModelRequestEnvelope,
)
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.capabilities.model.serving.endpoint import (
    JsonHttpResponse,
    ModelEndpointError,
    ModelEndpointRequestRejected,
    ModelEndpointRequest,
    ModelEndpointRoute,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers import NativeModelProviderEndpoint
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionController
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionLaneKind
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime


class Transport:
    def __init__(self, response: JsonHttpResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object], float]] = []
        self.last_headers: tuple[tuple[str, str], ...] = ()

    async def post_json(
        self, url: str, body: dict[str, object], *, timeout_s: float,
        headers: tuple[tuple[str, str], ...] = (),
    ) -> JsonHttpResponse:
        self.last_headers = headers
        self.calls.append((url, body, timeout_s))
        return self.response


def _envelope(request_id: str = "rq-1") -> ModelRequestEnvelope:
    return ModelRequestEnvelope(
        schema_version="model-request.v1", request_id=request_id,
        context=ExecutionContext("run", "trace", "span"), role="planner",
        model=ImmutableModelIdentity("planner", "qwen", "rev", "sglang", "1", "bfloat16", None, 8192),
        prompt_generation_id="prompt-gen", prompt_id="planner.prompt", prompt_digest="d" * 64,
        request_body=ArtifactBlobRef("f" * 64, 2, "application/json"),
    )


def _request(*, deployment_id: str = "dep-1", generation: str = "a" * 64) -> ModelEndpointRequest:
    return ModelEndpointRequest(
        request=_envelope(), deployment_id=deployment_id, deployment_generation=generation,
        body={"model": "qwen", "messages": [{"role": "user", "content": "x"}]},
    )


@pytest.fixture
def endpoint_group():
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group(f"test-model-endpoint:{uuid4().hex}")
    try:
        yield runtime, group
    finally:
        runtime.close()


def test_native_model_provider_endpoint_is_bound_to_exact_deployment_route(endpoint_group) -> None:
    runtime, group = endpoint_group
    transport = Transport(JsonHttpResponse(200, {
        "choices": [{"message": {"content": '{"action_type":"wait"}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
    }))
    route = ModelEndpointRoute("dep-1", "a" * 64, "http://127.0.0.1:30000")
    endpoint = NativeModelProviderEndpoint(route=route, transport=transport, task_group=group, admission=ModelAdmissionController(1))

    result = endpoint.complete(_request())

    assert result.request_id == "rq-1"
    assert result.deployment_id == "dep-1"
    assert result.output_tokens == 4
    assert result.usage["prompt_tokens"] == 12
    assert len(transport.calls) == 1
    url, body, timeout_s = transport.calls[0]
    assert url == "http://127.0.0.1:30000/v1/chat/completions"
    assert isinstance(body, bytes)
    assert json.loads(body) == {"model": "qwen", "messages": [{"role": "user", "content": "x"}]}
    assert 0.0 < timeout_s <= route.timeout_s
    tasks = runtime.topology_snapshot().groups[0].tasks
    assert len(tasks) == 1
    assert tasks[0].lane_kind is ExecutionLaneKind.ASYNC_IO
    assert tasks[0].execution_done


def test_native_model_provider_endpoint_rejects_route_identity_drift_before_transport(endpoint_group) -> None:
    _runtime, group = endpoint_group
    transport = Transport(JsonHttpResponse(200, {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}))
    endpoint = NativeModelProviderEndpoint(
        route=ModelEndpointRoute("dep-1", "a" * 64, "https://model.example"),
        transport=transport,
        task_group=group,
        admission=ModelAdmissionController(1),
    )
    with pytest.raises(ModelEndpointError, match="deployment"):
        endpoint.complete(_request(deployment_id="dep-2"))
    assert transport.calls == []


def test_native_model_provider_endpoint_rejects_ambiguous_response_shape(endpoint_group) -> None:
    _runtime, group = endpoint_group
    transport = Transport(JsonHttpResponse(200, {"choices": []}))
    endpoint = NativeModelProviderEndpoint(
        route=ModelEndpointRoute("dep-1", "a" * 64, "https://model.example"),
        transport=transport,
        task_group=group,
        admission=ModelAdmissionController(1),
    )
    with pytest.raises(ModelEndpointError, match="exactly one choice"):
        endpoint.complete(_request())


def test_native_model_provider_endpoint_preserves_structured_http_error_detail(endpoint_group) -> None:
    _runtime, group = endpoint_group
    transport = Transport(JsonHttpResponse(400, {
        "message": "No user query found in messages.",
        "code": 400,
    }))
    endpoint = NativeModelProviderEndpoint(
        route=ModelEndpointRoute("dep-1", "a" * 64, "https://model.example"),
        transport=transport,
        task_group=group,
        admission=ModelAdmissionController(1),
    )
    with pytest.raises(
        ModelEndpointRequestRejected,
        match="No user query found in messages",
    ) as raised:
        endpoint.complete(_request())
    assert raised.value.status_code == 400
    assert raised.value.affects_replica_health is False


def test_endpoint_contract_rejects_opaque_request_and_freezes_http_response() -> None:
    with pytest.raises(TypeError, match="request/operation envelope"):
        ModelEndpointRequest(
            request=object(), deployment_id="dep-1", deployment_generation="a" * 64,
            body={"model": "qwen", "messages": [{"role": "user", "content": "x"}]},
        )
    body = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    response = JsonHttpResponse(200, body)
    body["choices"][0]["message"]["content"] = "caller-mutated"
    assert response.body["choices"][0]["message"]["content"] == "ok"
    with pytest.raises(TypeError):
        response.body["choices"][0]["text"] = "tampered"
    with pytest.raises(ValueError, match="HTTP status"):
        JsonHttpResponse(600, {"error": "bad"})

class ExchangeObserver:
    observer_id = "raw-ledger"

    def __init__(self) -> None:
        self.exchanges = []

    def on_exchange(self, request, response, started_monotonic_ns, completed_monotonic_ns) -> None:
        self.exchanges.append(
            (request, response, started_monotonic_ns, completed_monotonic_ns)
        )

    def on_failure(
        self, request, error, started_monotonic_ns, completed_monotonic_ns,
    ) -> None:
        self.exchanges.append(
            (request, error, started_monotonic_ns, completed_monotonic_ns)
        )


def test_model_endpoint_observer_receives_exact_wire_bodies_and_timing(endpoint_group) -> None:
    runtime, group = endpoint_group
    wire_request = b'{"messages":[{"role":"user","content":"x"}],"model":"qwen"}'
    wire_response = b'{"choices":[{"text":"ok"}]}'
    observer = ExchangeObserver()
    transport = Transport(JsonHttpResponse(
        200, {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
        raw_body=wire_response, request_body=wire_request,
    ))
    endpoint = NativeModelProviderEndpoint(
        route=ModelEndpointRoute("dep-1", "a" * 64, "https://model.example"),
        transport=transport, task_group=group, admission=ModelAdmissionController(1),
        observers=(observer,),
    )
    assert endpoint.complete(_request()).text == "ok"
    assert len(observer.exchanges) == 1
    captured_request, captured_response, started, completed = observer.exchanges[0]
    assert captured_request.request.request_id == "rq-1"
    assert captured_response.request_body == wire_request
    assert captured_response.raw_body == wire_response
    assert completed >= started

def test_native_model_provider_endpoint_preserves_function_tool_calls(endpoint_group) -> None:
    _runtime, group = endpoint_group
    transport = Transport(JsonHttpResponse(200, {
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "wait", "arguments": '{"ms":1000}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
    }))
    endpoint = NativeModelProviderEndpoint(
        route=ModelEndpointRoute("dep-1", "a" * 64, "https://model.example"),
        transport=transport,
        task_group=group,
        admission=ModelAdmissionController(1),
    )

    result = endpoint.complete(_request())

    assert result.text == ""
    assert result.tool_calls[0]["function"]["name"] == "wait"
    assert result.tool_calls[0]["function"]["arguments"]["ms"] == 1000


class StreamTransport:
    def __init__(self, events, *, status_code=200, raw_body=b"raw-sse") -> None:
        self.events=tuple(events)
        self.status_code=status_code
        self.raw_body=raw_body
        self.calls=[]

    async def post_json(self, *args, **kwargs):
        raise AssertionError("stream test must not use post_json")

    async def post_sse(
        self, url, body, *, timeout_s, idle_timeout_s, on_event, headers=(),
    ):
        from noetrium_platform.capabilities.model.serving.endpoint import (
            SseHttpResponse,
        )
        self.calls.append(
            (url,body,timeout_s,idle_timeout_s,headers)
        )
        for event in self.events:
            on_event(event)
        return SseHttpResponse(
            status_code=self.status_code,
            response_headers=(("Content-Type","text/event-stream"),),
            request_body=b'{"wire":"request"}',
            raw_body=self.raw_body,
            event_count=len(self.events),
        )


class StreamExchangeObserver(ExchangeObserver):
    def on_stream_exchange(
        self, request, response, started_monotonic_ns, completed_monotonic_ns,
    ) -> None:
        self.exchanges.append(
            ("stream",request,response,started_monotonic_ns,completed_monotonic_ns)
        )


def _responses_endpoint(group, transport, *, observers=()):
    return NativeModelProviderEndpoint(
        route=ModelEndpointRoute(
            "dep-1","a"*64,"https://model.example",
            completion_path="/v1/responses",
        ),
        transport=transport,
        task_group=group,
        admission=ModelAdmissionController(1),
        observers=observers,
    )


def test_native_endpoint_stream_accumulates_and_observes_exact_raw_exchange(endpoint_group):
    _runtime,group=endpoint_group
    from noetrium_platform.capabilities.model.serving.endpoint import (
        RawServerSentEvent,
        ModelStreamEventKind,
    )
    events=(
        RawServerSentEvent(
            "response.output_text.delta",
            b'{"type":"response.output_text.delta","delta":"O"}',
        ),
        RawServerSentEvent(
            "response.output_text.delta",
            b'{"type":"response.output_text.delta","delta":"K"}',
        ),
        RawServerSentEvent(
            "response.completed",
            b'{"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":2,"output_tokens":2,"total_tokens":4}}}',
        ),
    )
    transport=StreamTransport(events,raw_body=b"exact-stream-wire")
    observer=StreamExchangeObserver()
    endpoint=_responses_endpoint(group,transport,observers=(observer,))
    seen=[]
    result=endpoint.stream(_request(),seen.append,stream_idle_timeout_s=7)

    assert result.text=="OK"
    assert result.finish_reason=="stop"
    assert result.input_tokens==2
    assert result.output_tokens==2
    assert [row.kind for row in seen] == [
        ModelStreamEventKind.TEXT_DELTA,
        ModelStreamEventKind.TEXT_DELTA,
        ModelStreamEventKind.USAGE,
        ModelStreamEventKind.COMPLETED,
    ]
    assert [row.sequence for row in seen] == [1,2,3,4]
    assert len(transport.calls)==1
    url,body,timeout_s,idle_timeout_s,_headers=transport.calls[0]
    assert url=="https://model.example/v1/responses"
    assert isinstance(body, bytes)
    assert json.loads(body)["stream"] is True
    assert 0 < idle_timeout_s <= timeout_s
    assert len(observer.exchanges)==1
    tag,_request_seen,response_seen,started,completed=observer.exchanges[0]
    assert tag=="stream"
    assert response_seen.request_body==b'{"wire":"request"}'
    assert response_seen.raw_body==b"exact-stream-wire"
    assert response_seen.event_count==3
    assert completed >= started


def test_native_endpoint_stream_fails_closed_without_terminal_event(endpoint_group):
    _runtime,group=endpoint_group
    from noetrium_platform.capabilities.model.serving.endpoint import RawServerSentEvent
    transport=StreamTransport((
        RawServerSentEvent(
            "response.output_text.delta",
            b'{"type":"response.output_text.delta","delta":"partial"}',
        ),
    ))
    endpoint=_responses_endpoint(group,transport)
    with pytest.raises(ModelEndpointError,match="terminal event"):
        endpoint.stream(_request(),lambda _event: None)


def test_native_endpoint_stream_rejects_observer_without_stream_capture(endpoint_group):
    _runtime,group=endpoint_group
    from noetrium_platform.capabilities.model.serving.endpoint import RawServerSentEvent
    events=(
        RawServerSentEvent(
            "response.completed",
            b'{"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":1,"output_tokens":1}}}',
        ),
    )
    endpoint=_responses_endpoint(
        group,
        StreamTransport(events),
        observers=(ExchangeObserver(),),
    )
    with pytest.raises(ModelEndpointError,match="capture is unavailable"):
        endpoint.stream(_request(),lambda _event: None)


class _CloseTrackingTransport:
    def __init__(self, responses):
        self.responses=list(responses)
        self.calls=[]
        self.closed=0
    async def post_json(self,url,body,*,timeout_s,headers=()):
        self.calls.append((url,body,timeout_s,headers))
        return self.responses.pop(0)
    async def aclose(self):
        self.closed += 1


def test_native_endpoint_closes_owned_transport_once(endpoint_group):
    _runtime,group=endpoint_group
    transport=_CloseTrackingTransport([
        JsonHttpResponse(200,{
            "choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],
        }),
    ])
    endpoint=NativeModelProviderEndpoint(
        route=ModelEndpointRoute("dep-1","a"*64,"https://model.example"),
        transport=transport,
        task_group=group,
        admission=ModelAdmissionController(1),
    )
    endpoint.close()
    endpoint.close()
    assert transport.closed==1
    with pytest.raises(ModelEndpointError,match="closed"):
        endpoint.complete(_request())


def test_native_endpoint_does_not_close_external_transport(endpoint_group):
    _runtime,group=endpoint_group
    transport=_CloseTrackingTransport([])
    endpoint=NativeModelProviderEndpoint(
        route=ModelEndpointRoute("dep-1","a"*64,"https://model.example"),
        transport=transport,
        task_group=group,
        admission=ModelAdmissionController(1),
        owns_transport=False,
    )
    endpoint.close()
    assert transport.closed==0


def _operation_request(
    capability_id: str,
    input_schema_id: str,
    output_schema_id: str,
    body: dict[str, object],
) -> ModelEndpointRequest:
    envelope=ModelOperationEnvelope(
        schema_version="model-operation.v1",
        request_id=f"op-{capability_id}",
        context=ExecutionContext("run-op","trace-op","span-op"),
        role="scientist",
        model=ImmutableModelIdentity(
            "qwen","qwen","rev","vllm","1","bfloat16",None,8192
        ),
        capability_id=capability_id,
        input_schema_id=input_schema_id,
        output_schema_id=output_schema_id,
        request_body=ArtifactBlobRef("e" * 64,2,"application/json"),
    )
    return ModelEndpointRequest(
        request=envelope,
        deployment_id="dep-1",
        deployment_generation="a" * 64,
        body=body,
    )


def test_native_endpoint_dispatches_embedding_through_operation_registry_with_auth(
    endpoint_group,
) -> None:
    _runtime,group=endpoint_group
    transport=Transport(JsonHttpResponse(
        200,
        {
            "data":[
                {"index":0,"embedding":[1.0,2.0]},
                {"index":1,"embedding":[3.0,4.0]},
            ],
            "usage":{"prompt_tokens":2},
        },
    ))
    endpoint=NativeModelProviderEndpoint(
        route=ModelEndpointRoute(
            "dep-1","a" * 64,"https://model.example"
        ),
        transport=transport,
        task_group=group,
        admission=ModelAdmissionController(2),
        api_key="secret-token",
    )
    result=endpoint.complete(_operation_request(
        "embedding",
        "model.embedding.input.v1",
        "model.embedding.output.v1",
        {"texts":("alpha","beta"),"normalize":False},
    ))
    assert result.payload["vectors"] == ((1.0,2.0),(3.0,4.0))
    assert transport.calls[0][0] == "https://model.example/v1/embeddings"
    assert isinstance(transport.calls[0][1], bytes)
    assert json.loads(transport.calls[0][1]) == {
        "model":"qwen",
        "input":["alpha","beta"],
        "encoding_format":"float",
    }
    assert transport.last_headers == (
        ("Authorization","Bearer secret-token"),
    )


def test_native_endpoint_unknown_typed_operation_uses_qualified_route_passthrough(
    endpoint_group,
) -> None:
    _runtime,group=endpoint_group
    transport=Transport(JsonHttpResponse(
        200,
        {"mode":"policy","rollouts":[{"predicted_state":{"x":1}}]},
    ))
    endpoint=NativeModelProviderEndpoint(
        route=ModelEndpointRoute(
            "dep-1",
            "a" * 64,
            "https://model.example",
            completion_path="/v1/world-model",
        ),
        transport=transport,
        task_group=group,
        admission=ModelAdmissionController(1),
        api_key="secret-token",
    )
    result=endpoint.complete(_operation_request(
        "world-model",
        "model.world-model.input.v1",
        "model.world-model.output.v1",
        {"mode":"policy","observations":(),"candidates":1},
    ))
    assert result.payload["mode"] == "policy"
    assert transport.calls[0][0] == "https://model.example/v1/world-model"
    assert isinstance(transport.calls[0][1], bytes)
    assert json.loads(transport.calls[0][1])["model"] == "qwen"
    assert transport.last_headers == (
        ("Authorization","Bearer secret-token"),
    )
