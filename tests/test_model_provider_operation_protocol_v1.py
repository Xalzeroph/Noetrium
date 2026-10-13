from __future__ import annotations

from noetrium_platform.capabilities.model.request.api import ModelOperationEnvelope
from noetrium_platform.capabilities.model.serving.provider import (
    NativeModelOperationProtocolRegistry,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity
from noetrium_platform.substrate.api import ArtifactBlobRef


def _envelope(capability_id: str) -> ModelOperationEnvelope:
    return ModelOperationEnvelope(
        schema_version="model-operation.v1",
        request_id=f"op-{capability_id}",
        context=ExecutionContext("run","trace","span"),
        role="model",
        model=ImmutableModelIdentity(
            "logical","provider-model","rev","vllm","1","bf16",None,8192
        ),
        capability_id=capability_id,
        input_schema_id=f"model.{capability_id}.input.v1",
        output_schema_id=f"model.{capability_id}.output.v1",
        request_body=ArtifactBlobRef("a" * 64,1,"application/json"),
    )


def test_operation_plan_auth_secret_is_not_part_of_repr_or_identity() -> None:
    registry=NativeModelOperationProtocolRegistry()
    first=registry.plan(
        _envelope("embedding"),
        {"texts":("a",),"normalize":False},
        default_path="/unused",
        provider_id="openai",
        auth_kind="bearer-optional",
        api_key="secret-a",
    )
    second=registry.plan(
        _envelope("embedding"),
        {"texts":("a",),"normalize":False},
        default_path="/unused",
        provider_id="openai",
        auth_kind="bearer-optional",
        api_key="secret-b",
    )
    assert first.plan_digest == second.plan_digest
    assert "secret-a" not in repr(first)
    assert first.headers == (("Authorization","Bearer secret-a"),)


def test_rerank_protocol_preserves_candidate_identity_through_wire_index() -> None:
    registry=NativeModelOperationProtocolRegistry()
    plan=registry.plan(
        _envelope("ranking"),
        {
            "query":"best",
            "candidates":(
                {"candidate_id":"a","text":"A"},
                {"candidate_id":"b","text":"B"},
            ),
            "top_k":1,
        },
        default_path="/unused",
        provider_id="vllm",
        auth_kind="bearer-optional",
        api_key="",
    )
    assert plan.path == "/v1/rerank"
    assert plan.body["documents"] == ("A","B")
    assert plan.body["top_n"] == 1
    decoded=registry.decode(
        plan,
        {"results":({"index":1,"relevance_score":0.9},)},
    )
    assert decoded["results"][0]["candidate_id"] == "b"
    assert decoded["results"][0]["score"] == 0.9


def test_custom_typed_operation_uses_configured_route_and_runtime_owned_model() -> None:
    registry=NativeModelOperationProtocolRegistry()
    envelope=_envelope("world-model")
    plan=registry.plan(
        envelope,
        {"mode":"policy","candidates":1},
        default_path="/v1/world-model",
        provider_id="vllm",
        auth_kind="bearer-optional",
        api_key="",
    )
    assert plan.path == "/v1/world-model"
    assert plan.body["model"] == envelope.model.model_id
    assert plan.body["mode"] == "policy"
