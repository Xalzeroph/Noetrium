from __future__ import annotations

from components.api import (
    ReferenceAgentAction,
    ReferenceAgentActionKind,
    ReferenceAgentDecisionCodec,
    ReferenceAgentGenerationControls,
    ReferenceAgentHooks,
    ReferenceAgentModelResponse,
    ReferenceAgentOutputMode,
    ToolDefinition,
    ToolRegistry,
)


def test_registry_publishes_stable_function_schema() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        "lookup",
        "Look up a value",
        "lookup.input.v1",
        input_schema={"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
    ), lambda _args: None)
    schema = registry.model_tool_schema()
    assert schema[0]["function"]["name"] == "lookup"
    assert registry.model_tool_schema() == schema
    assert len(registry.model_tool_schema_sha256) == 64


def test_generation_controls_build_native_fields() -> None:
    controls = ReferenceAgentGenerationControls(
        mode=ReferenceAgentOutputMode.JSON_SCHEMA,
        schema_name="agent_decision",
        schema={"type": "object"},
    )
    assert controls.request_fields()["response_format"]["type"] == "json_schema"
    assert ReferenceAgentGenerationControls().request_fields(
        ({"type": "function"},)
    )["tool_choice"] == "auto"


def test_decision_codec_accepts_native_tool_call_without_text() -> None:
    decision = ReferenceAgentDecisionCodec.decode(ReferenceAgentModelResponse(
        tool_calls=({"id": "call-1", "type": "function", "function": {
            "name": "lookup", "arguments": '{"key":"x"}'
        }},),
    ))
    assert decision.action.kind is ReferenceAgentActionKind.TOOL
    assert decision.action.name == "lookup"
    assert decision.action.arguments["key"] == "x"


def test_decision_codec_accepts_strict_json_final() -> None:
    decision = ReferenceAgentDecisionCodec.decode(
        ReferenceAgentModelResponse(text='{"kind":"final","content":"done"}')
    )
    assert decision.action == ReferenceAgentAction(
        ReferenceAgentActionKind.FINAL, "final", content="done"
    )


def test_hooks_are_extension_nodes() -> None:
    hooks = ReferenceAgentHooks(before_turn=lambda _state: None)
    assert callable(hooks.before_turn)

if __name__ == "__main__":
    for name, value in globals().copy().items():
        if name.startswith("test_"):
            value()
    print("HARNESS_TESTS_OK")
