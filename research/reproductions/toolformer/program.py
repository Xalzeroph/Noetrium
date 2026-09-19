from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    JsonObject,
    JsonValue,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import TOOLFORMER_FIDELITY

_MODEL_AGENT = "toolformer.gpt-j"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
        raise ValueError(f"Toolformer {field} must be text")
    return value


def toolformer_initial_state(*, instruction: str) -> JsonObject:
    return {
        "instruction": _text(instruction, "instruction"),
        "generated_text": "",
        "tool_trace": (),
        "pending_capability_id": "",
        "pending_arguments": {},
        "tool_call_count": 0,
        "model_call_count": 0,
        "final_answer": "",
    }


def _model_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "instruction": request.state.get("instruction"),
        "generated_text": request.state.get("generated_text", ""),
        "tool_trace": request.state.get("tool_trace", ()),
        "api_top_k": TOOLFORMER_FIDELITY.evaluation_api_top_k,
        "max_api_calls": TOOLFORMER_FIDELITY.evaluation_max_api_calls_per_input,
        "api_start_token": TOOLFORMER_FIDELITY.api_call_start_token,
        "api_end_token": TOOLFORMER_FIDELITY.api_call_end_token,
        "api_result_arrow": TOOLFORMER_FIDELITY.api_result_arrow,
    }


def _parse_model_output(
    value: JsonValue,
) -> tuple[str, JsonObject | None, str | None]:
    if isinstance(value, str):
        return value, None, value
    if not isinstance(value, Mapping):
        raise TypeError("Toolformer model output must be text or object")
    text = value.get("text", value.get("generated_text", ""))
    text = _text(text, "generated text", allow_empty=True)
    raw_call = value.get("api_call")
    final = value.get("final_answer")
    final_text = (
        None
        if final is None
        else _text(final, "final answer", allow_empty=True)
    )
    if raw_call is None:
        return text, None, final_text if final_text is not None else text
    if not isinstance(raw_call, Mapping):
        raise TypeError("Toolformer api_call must be an object")
    capability_id = _text(
        raw_call.get("capability_id"),
        "api capability_id",
    )
    arguments = raw_call.get("arguments", {})
    if not isinstance(arguments, Mapping):
        raise TypeError("Toolformer api call arguments must be an object")
    return (
        text,
        {
            "capability_id": capability_id,
            "arguments": dict(arguments),
        },
        final_text,
    )


def _record_model(
    allowed_capabilities: tuple[str, ...],
    tools_enabled: bool,
):
    allowed = set(allowed_capabilities)

    def record(request: MethodNodeRequest) -> MethodNodeResult:
        text, api_call, final = _parse_model_output(request.previous_value)
        count = request.state.get("model_call_count", 0)
        if type(count) is not int or count < 0:
            raise ValueError("Toolformer model_call_count must be non-negative")
        model_calls = count + 1

        if not tools_enabled or api_call is None:
            answer = text if final is None else final
            return MethodNodeResult(
                value={"final_answer": answer},
                state_update={
                    "generated_text": text,
                    "final_answer": answer,
                    "model_call_count": model_calls,
                    "pending_capability_id": "",
                    "pending_arguments": {},
                },
                next_node="return",
            )

        capability_id = _text(
            api_call.get("capability_id"),
            "api capability_id",
        )
        if capability_id not in allowed:
            raise ValueError(
                "Toolformer generated API call escaped capability closure"
            )
        tool_calls = request.state.get("tool_call_count", 0)
        if type(tool_calls) is not int or tool_calls < 0:
            raise ValueError("Toolformer tool_call_count must be non-negative")
        if tool_calls >= TOOLFORMER_FIDELITY.evaluation_max_api_calls_per_input:
            return MethodNodeResult(
                value={"final_answer": text},
                state_update={
                    "generated_text": text,
                    "final_answer": text,
                    "model_call_count": model_calls,
                    "pending_capability_id": "",
                    "pending_arguments": {},
                },
                next_node="return",
            )
        return MethodNodeResult(
            value={"api_call": api_call},
            state_update={
                "generated_text": text,
                "model_call_count": model_calls,
                "pending_capability_id": capability_id,
                "pending_arguments": api_call.get("arguments", {}),
            },
            next_node="prepare_tool",
        )

    return record


def _prepare_tool(request: MethodNodeRequest) -> MethodNodeResult:
    capability_id = _text(
        request.state.get("pending_capability_id"),
        "pending capability_id",
    )
    arguments = request.state.get("pending_arguments", {})
    if not isinstance(arguments, Mapping):
        raise TypeError("Toolformer pending_arguments must be an object")
    return MethodNodeResult(
        value={
            "capability_id": capability_id,
            "arguments": dict(arguments),
        }
    )


def _tool_target(request: MethodNodeRequest) -> str:
    return _text(
        request.state.get("pending_capability_id"),
        "pending capability_id",
    )


def _record_tool(request: MethodNodeRequest) -> MethodNodeResult:
    capability_id = _tool_target(request)
    trace = request.state.get("tool_trace", ())
    if isinstance(trace, (str, bytes, bytearray)) or not isinstance(trace, Sequence):
        raise TypeError("Toolformer tool_trace must be a sequence")
    count = request.state.get("tool_call_count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("Toolformer tool_call_count must be non-negative")
    tool_result = thaw_json(request.previous_value)
    row: JsonObject = {
        "capability_id": capability_id,
        "arguments": request.state.get("pending_arguments", {}),
        "result": tool_result,
    }
    return MethodNodeResult(
        value=row,
        state_update={
            "tool_trace": (*tuple(trace), row),
            "tool_call_count": count + 1,
            "pending_capability_id": "",
            "pending_arguments": {},
        },
        next_node="model",
        checkpoint=True,
        checkpoint_value={
            "tool_call_count": count + 1,
            "capability_id": capability_id,
        },
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={
            "final_answer": request.state.get("final_answer", ""),
            "generated_text": request.state.get("generated_text", ""),
            "tool_call_count": request.state.get("tool_call_count", 0),
            "model_call_count": request.state.get("model_call_count", 0),
            "tool_trace": request.state.get("tool_trace", ()),
        }
    )


def build_toolformer_method_program(
    tool_capability_ids: tuple[str, ...],
    *,
    tools_enabled: bool = True,
) -> MethodProgram:
    if type(tools_enabled) is not bool:
        raise TypeError("Toolformer tools_enabled must be boolean")
    if type(tool_capability_ids) is not tuple:
        raise TypeError("Toolformer capability closure must be a tuple")
    if tools_enabled and not tool_capability_ids:
        raise ValueError("enabled Toolformer requires a tool capability closure")
    if any(type(row) is not str or not row.strip() for row in tool_capability_ids):
        raise ValueError("Toolformer capability ids must be canonical text")
    if len(tool_capability_ids) != len(set(tool_capability_ids)):
        raise ValueError("Toolformer capability ids must be unique")

    configuration: JsonObject = {
        "publication_id": TOOLFORMER_FIDELITY.publication_id,
        "base_model": TOOLFORMER_FIDELITY.base_model,
        "tools_enabled": tools_enabled,
        "tool_capability_ids": tool_capability_ids,
        "api_top_k": TOOLFORMER_FIDELITY.evaluation_api_top_k,
        "max_api_calls_per_input": (
            TOOLFORMER_FIDELITY.evaluation_max_api_calls_per_input
        ),
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="toolformer",
            implementation_version="neurips-2023-final",
            abi_version="noetrium.method-machine.v1",
            schema_version="toolformer.inference.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="model")
    builder.agent(
        "model",
        "toolformer.decode",
        _MODEL_AGENT,
        ("record_model",),
        view_handler=_model_view,
        max_visits=2,
    )
    builder.route(
        "record_model",
        "toolformer.decode.record",
        _record_model(tool_capability_ids, tools_enabled),
        ("prepare_tool", "return") if tools_enabled else ("return",),
        max_visits=2,
    )
    if tools_enabled:
        builder.compute(
            "prepare_tool",
            "toolformer.api.prepare",
            _prepare_tool,
            ("tool",),
            max_visits=1,
        )
        builder.dynamic_capability(
            "tool",
            "toolformer.api.execute",
            tool_capability_ids,
            _tool_target,
            ("record_tool",),
            effect_class=EffectClass.RECONCILABLE,
            max_visits=1,
            evidence_obligations=("toolformer.api-effect",),
        )
        builder.compute(
            "record_tool",
            "toolformer.api.record",
            _record_tool,
            ("model",),
            max_visits=1,
        )
    builder.return_node("return", "toolformer.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=tool_capability_ids if tools_enabled else (),
        execution_class=MethodExecutionClass.CHECKPOINTABLE,
        evidence_obligations=(
            (
                "toolformer.model-decode",
                "toolformer.api-decision",
                "toolformer.api-effect",
            )
            if tools_enabled
            else (
                "toolformer.model-decode",
                "toolformer.api-decision",
            )
        ),
        metric_names=(
            "task_success",
            "tool_call_count",
            "model_call_count",
        ),
        artifact_kinds=("toolformer_tool_trace",),
    )


__all__ = ["build_toolformer_method_program", "toolformer_initial_state"]
