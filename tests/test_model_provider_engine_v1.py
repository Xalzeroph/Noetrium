from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import thaw_json

from noetrium_platform.capabilities.model.serving.provider import (
    CANONICAL_MODEL_SEED_MAX,
    ModelProviderRequestPlanner,
    ModelProviderRequestUnsupported,
    NativeModelProviderProfileResolver,
    NativeModelProviderProtocolRegistry,
)


def _resolver():
    return NativeModelProviderProfileResolver()


def _plan(engine: str, body: dict, *, logical="Qwen3-8B", provider_model=None):
    profile=_resolver().resolve(
        logical_model_name=logical,
        provider_model_name=provider_model or logical,
        model_engine=engine,
    )
    return ModelProviderRequestPlanner().plan(profile,body)


def test_vllm_profile_is_noetrium_native_and_capability_aware():
    profile=_resolver().resolve(
        logical_model_name="Qwen3-8B",
        provider_model_name="Qwen3-8B",
        model_engine="vllm",
    )
    assert profile.provider_id=="vllm"
    assert profile.protocol_id=="openai.chat-completions"
    assert "chat_template_kwargs" in profile.passthrough_parameters
    assert {"generation","seeded_sampling","structured_output","tools","reasoning","multimodal"} <= set(profile.features)


def test_provider_planner_keeps_provider_model_name_and_splits_extensions():
    body={
        "model":"Qwen3-8B",
        "messages":({"role":"user","content":"Return JSON"},),
        "response_format":{"type":"json_object"},
        "seed":7,
        "temperature":0.0,
        "top_p":1.0,
        "chat_template_kwargs":{"enable_thinking":False},
    }
    plan=_plan("vllm",body)
    assert plan.backend_model=="Qwen3-8B"
    assert plan.standard_body["seed"]==7
    assert "chat_template_kwargs" not in plan.standard_body
    assert plan.extra_body=={"chat_template_kwargs":{"enable_thinking":False}}


def test_provider_planner_rejects_seed_outside_signed_int64():
    body={"model":"Qwen3-8B","messages":({"role":"user","content":"x"},),"seed":CANONICAL_MODEL_SEED_MAX+1}
    with pytest.raises(ModelProviderRequestUnsupported,match="signed-int64"):
        _plan("vllm",body)


def test_provider_planner_rejects_hidden_runtime_policy():
    body={"model":"Qwen3-8B","messages":({"role":"user","content":"x"},),"max_retries":3}
    with pytest.raises(ModelProviderRequestUnsupported,match="runtime-owned"):
        _plan("vllm",body)


def test_openai_protocol_merges_vllm_extensions_on_wire():
    body={
        "model":"Qwen3-8B",
        "messages":({"role":"user","content":"Return JSON"},),
        "max_tokens":32,
        "chat_template_kwargs":{"enable_thinking":False},
    }
    plan=_plan("vllm",body)
    wire=NativeModelProviderProtocolRegistry().encode(plan)
    assert wire.body["model"]=="Qwen3-8B"
    assert wire.body["chat_template_kwargs"]=={"enable_thinking":False}
    assert "extra_body" not in wire.body


def test_openai_protocol_normalizes_text_tools_and_usage():
    plan=_plan("vllm",{"model":"Qwen3-8B","messages":({"role":"user","content":"x"},)})
    result=NativeModelProviderProtocolRegistry().decode(plan,{
        "choices":[{
            "message":{
                "content":"",
                "tool_calls":[{
                    "id":"call-1","type":"function",
                    "function":{"name":"act","arguments":"{\"x\":1}"},
                }],
            },
            "finish_reason":"tool_calls",
        }],
        "usage":{"prompt_tokens":5,"completion_tokens":3,"total_tokens":8},
    })
    assert result.tool_calls[0]["function"]["arguments"]=={"x":1}
    assert result.usage["prompt_tokens"]==5


def test_anthropic_protocol_maps_system_tools_and_usage():
    body={
        "model":"claude-test",
        "messages":(
            {"role":"system","content":"You are precise."},
            {"role":"user","content":"Use tool."},
        ),
        "max_tokens":64,
        "tools":({
            "type":"function",
            "function":{"name":"lookup","description":"lookup","parameters":{"type":"object","properties":{}}},
        },),
        "tool_choice":"auto",
    }
    plan=_plan("anthropic",body,logical="claude-test")
    registry=NativeModelProviderProtocolRegistry()
    wire=registry.encode(plan,api_key="secret")
    assert wire.body["system"]=="You are precise."
    assert wire.body["tools"][0]["name"]=="lookup"
    assert ("x-api-key","secret") in wire.headers
    result=registry.decode(plan,{
        "content":[
            {"type":"text","text":"calling"},
            {"type":"tool_use","id":"tool-1","name":"lookup","input":{"q":"x"}},
        ],
        "stop_reason":"tool_use",
        "usage":{"input_tokens":7,"output_tokens":2},
    })
    assert result.text=="calling"
    assert result.tool_calls[0]["function"]["arguments"]=={"q":"x"}
    assert result.usage["prompt_tokens"]==7


def test_gemini_protocol_maps_generation_config_schema_and_tool_call():
    body={
        "model":"gemini-test",
        "messages":({"role":"user","content":"Return JSON"},),
        "max_tokens":40,
        "temperature":0.0,
        "response_format":{"type":"json_object"},
    }
    plan=_plan("gemini",body,logical="gemini-test")
    registry=NativeModelProviderProtocolRegistry()
    wire=registry.encode(plan,api_key="key")
    assert wire.body["generationConfig"]["maxOutputTokens"]==40
    assert wire.body["generationConfig"]["responseMimeType"]=="application/json"
    assert ("x-goog-api-key","key") in wire.headers
    result=registry.decode(plan,{
        "candidates":[{
            "content":{"parts":[
                {"text":"ok"},
                {"functionCall":{"name":"act","args":{"x":1}}},
            ]},
            "finishReason":"STOP",
        }],
        "usageMetadata":{"promptTokenCount":4,"candidatesTokenCount":2,"totalTokenCount":6},
    })
    assert result.text=="ok"
    assert result.tool_calls[0]["function"]["name"]=="act"
    assert result.usage["total_tokens"]==6


def test_unknown_provider_fails_closed():
    with pytest.raises(ModelProviderRequestUnsupported,match="no native provider protocol"):
        _resolver().resolve(
            logical_model_name="x",provider_model_name="x",model_engine="unknown-engine"
        )


def test_openai_protocol_preserves_reasoning_refusal_and_native_blocks():
    plan=_plan("vllm",{"model":"Qwen3-8B","messages":({"role":"user","content":"x"},)})
    result=NativeModelProviderProtocolRegistry().decode(plan,{
        "choices":[{
            "message":{
                "content":[{"type":"text","text":"answer","annotations":[{"type":"citation","url":"https://example.test"}]}],
                "reasoning_content":"private-reasoning-token-stream",
                "refusal":"cannot comply",
            },
            "finish_reason":"stop",
        }],
        "usage":{"prompt_tokens":2,"completion_tokens":4},
    })
    assert result.text=="answer"
    assert [block["kind"] for block in result.content_blocks] == [
        "text","reasoning","refusal"
    ]
    reasoning=result.content_blocks[1]
    assert reasoning["text"]=="private-reasoning-token-stream"
    assert reasoning["provider_payload"]["reasoning_content"]=="private-reasoning-token-stream"
    refusal=result.content_blocks[2]
    assert refusal["provider_payload"]["refusal"]=="cannot comply"
    assert result.content_blocks[0]["provider_payload"]["annotations"][0]["type"]=="citation"


def test_anthropic_protocol_preserves_signed_and_redacted_thinking_losslessly():
    plan=_plan(
        "anthropic",
        {
            "model":"claude-test",
            "messages":({"role":"user","content":"think"},),
            "max_tokens":64,
        },
        logical="claude-test",
    )
    result=NativeModelProviderProtocolRegistry().decode(plan,{
        "content":[
            {"type":"thinking","thinking":"reason","signature":"sig-opaque-123"},
            {"type":"redacted_thinking","data":"opaque-redacted-ciphertext"},
            {"type":"text","text":"answer"},
        ],
        "stop_reason":"end_turn",
        "usage":{"input_tokens":5,"output_tokens":7},
    })
    assert result.text=="answer"
    assert [block["kind"] for block in result.content_blocks] == [
        "reasoning","redacted_reasoning","text"
    ]
    thinking=result.content_blocks[0]
    assert thinking["signature"]=="sig-opaque-123"
    assert thinking["provider_payload"] == {
        "type":"thinking","thinking":"reason","signature":"sig-opaque-123"
    }
    assert result.content_blocks[1]["provider_payload"]["data"]=="opaque-redacted-ciphertext"


def test_gemini_protocol_preserves_thought_signature_on_reasoning_and_tool_call():
    plan=_plan(
        "gemini",
        {"model":"gemini-test","messages":({"role":"user","content":"think and call"},)},
        logical="gemini-test",
    )
    result=NativeModelProviderProtocolRegistry().decode(plan,{
        "candidates":[{
            "content":{"parts":[
                {"thought":True,"text":"reasoning","thoughtSignature":"opaque-thought-1"},
                {
                    "functionCall":{"name":"act","args":{"x":1}},
                    "thoughtSignature":"opaque-tool-thought-2",
                },
                {"text":"answer"},
            ]},
            "finishReason":"STOP",
        }],
        "usageMetadata":{"promptTokenCount":3,"candidatesTokenCount":5,"totalTokenCount":8},
    })
    assert result.text=="answer"
    assert [block["kind"] for block in result.content_blocks] == [
        "reasoning","tool_call","text"
    ]
    assert result.content_blocks[0]["provider_payload"]["thoughtSignature"]=="opaque-thought-1"
    assert result.content_blocks[1]["provider_payload"]["thoughtSignature"]=="opaque-tool-thought-2"
    assert result.content_blocks[1]["tool_call"]["function"]["name"]=="act"


def test_openai_reasoning_state_round_trips_into_next_turn_wire_message():
    first=_plan(
        "vllm",
        {"model":"Qwen3-8B","messages":({"role":"user","content":"think"},)},
    )
    registry=NativeModelProviderProtocolRegistry()
    decoded=registry.decode(first,{
        "choices":[{
            "message":{
                "content":"answer",
                "reasoning_content":"opaque-qwen-reasoning",
                "tool_calls":[{
                    "id":"call-1",
                    "type":"function",
                    "function":{"name":"act","arguments":"{\"x\":1}"},
                }],
            },
            "finish_reason":"tool_calls",
        }],
        "usage":{"prompt_tokens":2,"completion_tokens":3},
    })
    next_plan=_plan(
        "vllm",
        {
            "model":"Qwen3-8B",
            "messages":(
                {"role":"assistant","content_blocks":decoded.content_blocks},
                {"role":"user","content":"continue"},
            ),
        },
    )
    wire=registry.encode(next_plan)
    assistant=wire.body["messages"][0]
    assert assistant["reasoning_content"]=="opaque-qwen-reasoning"
    assert assistant["tool_calls"][0]["function"]["arguments"]=="{\"x\":1}"
    assert assistant["content"]=="answer"
    assert "content_blocks" not in assistant


def test_anthropic_signed_reasoning_round_trips_without_reordering_or_mutation():
    first=_plan(
        "anthropic",
        {
            "model":"claude-test",
            "messages":({"role":"user","content":"think"},),
            "max_tokens":64,
        },
        logical="claude-test",
    )
    registry=NativeModelProviderProtocolRegistry()
    decoded=registry.decode(first,{
        "content":[
            {"type":"thinking","thinking":"reason","signature":"sig-opaque"},
            {"type":"redacted_thinking","data":"ciphertext-opaque"},
            {"type":"tool_use","id":"tool-1","name":"lookup","input":{"q":"x"}},
        ],
        "stop_reason":"tool_use",
        "usage":{"input_tokens":2,"output_tokens":4},
    })
    next_plan=_plan(
        "anthropic",
        {
            "model":"claude-test",
            "messages":(
                {"role":"assistant","content_blocks":decoded.content_blocks},
                {"role":"user","content":"continue"},
            ),
            "max_tokens":64,
        },
        logical="claude-test",
    )
    wire=registry.encode(next_plan)
    assert thaw_json(wire.body["messages"][0]["content"]) == [
        {"type":"thinking","thinking":"reason","signature":"sig-opaque"},
        {"type":"redacted_thinking","data":"ciphertext-opaque"},
        {"type":"tool_use","id":"tool-1","name":"lookup","input":{"q":"x"}},
    ]


def test_gemini_thought_signatures_round_trip_exactly_in_part_order():
    first=_plan(
        "gemini",
        {"model":"gemini-test","messages":({"role":"user","content":"think"},)},
        logical="gemini-test",
    )
    registry=NativeModelProviderProtocolRegistry()
    decoded=registry.decode(first,{
        "candidates":[{
            "content":{"parts":[
                {"thought":True,"text":"reason","thoughtSignature":"sig-r"},
                {
                    "functionCall":{"name":"act","args":{"x":1}},
                    "thoughtSignature":"sig-call",
                },
                {"text":"answer"},
            ]},
            "finishReason":"STOP",
        }],
        "usageMetadata":{"promptTokenCount":2,"candidatesTokenCount":3,"totalTokenCount":5},
    })
    next_plan=_plan(
        "gemini",
        {
            "model":"gemini-test",
            "messages":(
                {"role":"assistant","content_blocks":decoded.content_blocks},
                {"role":"user","content":"continue"},
            ),
        },
        logical="gemini-test",
    )
    wire=registry.encode(next_plan)
    assert thaw_json(wire.body["contents"][0]["parts"]) == [
        {"thought":True,"text":"reason","thoughtSignature":"sig-r"},
        {
            "functionCall":{"name":"act","args":{"x":1}},
            "thoughtSignature":"sig-call",
        },
        {"text":"answer"},
    ]


def test_opaque_reasoning_state_cannot_cross_provider_boundary():
    first=_plan(
        "anthropic",
        {
            "model":"claude-test",
            "messages":({"role":"user","content":"think"},),
            "max_tokens":64,
        },
        logical="claude-test",
    )
    registry=NativeModelProviderProtocolRegistry()
    decoded=registry.decode(first,{
        "content":[
            {"type":"thinking","thinking":"reason","signature":"sig-private"},
            {"type":"text","text":"answer"},
        ],
        "stop_reason":"end_turn",
        "usage":{"input_tokens":2,"output_tokens":2},
    })
    next_plan=_plan(
        "vllm",
        {
            "model":"Qwen3-8B",
            "messages":(
                {"role":"assistant","content_blocks":decoded.content_blocks},
                {"role":"user","content":"continue"},
            ),
        },
    )
    with pytest.raises(ModelProviderRequestUnsupported,match="cannot cross provider boundary"):
        registry.encode(next_plan)


def test_openai_responses_protocol_replays_native_reasoning_and_maps_tools():
    base=_resolver().resolve(
        logical_model_name="Qwen3-8B",
        provider_model_name="Qwen3-8B",
        model_engine="vllm",
    )
    from noetrium_platform.capabilities.model.serving.provider import (
        provider_profile_for_protocol,
    )
    profile=provider_profile_for_protocol(base,"openai.responses")
    body={
        "model":"Qwen3-8B",
        "messages":(
            {
                "role":"assistant",
                "content":"previous",
                "content_blocks":(
                    {
                        "kind":"reasoning",
                        "provider_id":"vllm",
                        "provider_payload":{
                            "type":"reasoning",
                            "id":"rs_1",
                            "encrypted_content":"opaque-ciphertext",
                            "summary":[],
                        },
                    },
                ),
                "tool_calls":(
                    {
                        "id":"call-1",
                        "type":"function",
                        "function":{"name":"act","arguments":{"x":1}},
                    },
                ),
            },
            {
                "role":"tool",
                "tool_call_id":"call-1",
                "content":"done",
            },
            {"role":"user","content":"continue"},
        ),
        "tools":(
            {
                "type":"function",
                "function":{
                    "name":"act",
                    "description":"act",
                    "parameters":{"type":"object","properties":{"x":{"type":"integer"}}},
                },
            },
        ),
        "reasoning_effort":"high",
        "max_tokens":64,
    }
    plan=ModelProviderRequestPlanner().plan(profile,body)
    wire=NativeModelProviderProtocolRegistry().encode(plan)
    assert wire.body["model"]=="Qwen3-8B"
    assert wire.body["max_output_tokens"]==64
    assert wire.body["reasoning"]=={"effort":"high"}
    assert wire.body["tools"][0]["name"]=="act"
    assert wire.body["input"][0]["type"]=="reasoning"
    assert wire.body["input"][0]["encrypted_content"]=="opaque-ciphertext"
    assert any(item.get("type")=="function_call_output" for item in wire.body["input"])


def test_openai_responses_protocol_decodes_reasoning_function_call_and_usage():
    base=_resolver().resolve(
        logical_model_name="Qwen3-8B",
        provider_model_name="Qwen3-8B",
        model_engine="vllm",
    )
    from noetrium_platform.capabilities.model.serving.provider import (
        provider_profile_for_protocol,
    )
    profile=provider_profile_for_protocol(base,"openai.responses")
    plan=ModelProviderRequestPlanner().plan(
        profile,
        {
            "model":"Qwen3-8B",
            "messages":({"role":"user","content":"think and act"},),
        },
    )
    result=NativeModelProviderProtocolRegistry().decode(plan,{
        "id":"resp_1",
        "status":"completed",
        "output":[
            {
                "type":"reasoning",
                "id":"rs_1",
                "encrypted_content":"opaque",
                "summary":[{"type":"summary_text","text":"reason"}],
            },
            {
                "type":"function_call",
                "id":"fc_1",
                "call_id":"call_1",
                "name":"act",
                "arguments":"{\"x\":1}",
            },
            {
                "type":"message",
                "role":"assistant",
                "content":[{"type":"output_text","text":"answer","annotations":[]}],
            },
        ],
        "usage":{"input_tokens":3,"output_tokens":4,"total_tokens":7},
    })
    assert result.text=="answer"
    assert result.finish_reason=="stop"
    assert result.tool_calls[0]["function"]["arguments"]=={"x":1}
    assert result.usage["prompt_tokens"]==3
    assert result.usage["completion_tokens"]==4
    assert [block["kind"] for block in result.content_blocks] == [
        "reasoning","tool_call","text"
    ]
    assert result.content_blocks[0]["provider_payload"]["encrypted_content"]=="opaque"
