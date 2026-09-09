"""One-entry-point harness for downstream single-agent methods.

The harness owns model-output normalization, function-tool schema publication,
hook ordering, checkpoints, and the bounded ReAct loop. Downstream supplies a
policy and tool implementations through prescribed seams.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from noetrium.contracts.json import JsonValue, canonical_digest, freeze_json
from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from ..tools import ToolRegistry
from .contracts import (
    ReferenceAgentAction,
    ReferenceAgentActionKind,
    ReferenceAgentDecision,
    ReferenceAgentDecisionPort,
    ReferenceAgentObservation,
    ReferenceAgentRunResult,
    ReferenceAgentState,
    ReferenceAgentToolPort,
)
from .methods import ReferenceReActMethod
from .runtime import (
    NullReferenceAgentProgress,
    ReferenceAgentEvent,
    ReferenceAgentProgressPort,
)


class ReferenceAgentOutputMode(StrEnum):
    TEXT = "text"
    JSON_SCHEMA = "json_schema"
    TOOL_CALLING = "tool_calling"


@dataclass(frozen=True, slots=True)
class ReferenceAgentGenerationControls:
    """Provider-neutral output contract used by every model adapter."""

    mode: ReferenceAgentOutputMode = ReferenceAgentOutputMode.TOOL_CALLING
    schema_name: str | None = None
    schema: Mapping[str, JsonValue] | None = None
    tool_choice: str = "auto"
    strict: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.mode, ReferenceAgentOutputMode):
            raise TypeError("generation mode must be ReferenceAgentOutputMode")
        if self.mode is ReferenceAgentOutputMode.JSON_SCHEMA:
            if not isinstance(self.schema_name, str) or not self.schema_name.strip():
                raise ValueError("json-schema generation requires schema_name")
            if not isinstance(self.schema, Mapping):
                raise TypeError("json-schema generation requires schema")
        elif self.schema is not None or self.schema_name is not None:
            raise ValueError("schema fields are only valid for json-schema generation")
        if self.mode is ReferenceAgentOutputMode.TOOL_CALLING and self.tool_choice not in {
            "auto", "none", "required",
        }:
            raise ValueError("tool_choice must be auto, none, or required")
        if type(self.strict) is not bool:
            raise TypeError("generation strict must be bool")
        if self.schema is not None:
            object.__setattr__(self, "schema", freeze_json(self.schema))

    def request_fields(self, tool_schema: JsonValue = ()) -> dict[str, JsonValue]:
        """Build response_format/tools fields without provider-specific glue."""
        if self.mode is ReferenceAgentOutputMode.TEXT:
            return {}
        if self.mode is ReferenceAgentOutputMode.JSON_SCHEMA:
            return {"response_format": {"type": "json_schema", "json_schema": {
                "name": self.schema_name,
                "strict": self.strict,
                "schema": self.schema,
            }}}
        if not isinstance(tool_schema, (tuple, list)) or not tool_schema:
            raise ValueError("tool-calling generation requires a non-empty tool schema")
        return {"tools": freeze_json(tool_schema), "tool_choice": self.tool_choice}

    def digest(self, tool_schema: JsonValue = ()) -> str:
        return canonical_digest({
            "mode": self.mode.value,
            "schema_name": self.schema_name,
            "schema": self.schema,
            "tool_choice": self.tool_choice,
            "strict": self.strict,
            "tool_schema": tool_schema if self.mode is ReferenceAgentOutputMode.TOOL_CALLING else (),
        })


@dataclass(frozen=True, slots=True)
class ReferenceAgentModelResponse:
    text: str = ""
    tool_calls: JsonValue = ()

    def __post_init__(self) -> None:
        if type(self.text) is not str:
            raise TypeError("model response text must be string")
        object.__setattr__(self, "tool_calls", freeze_json(self.tool_calls))
        if not isinstance(self.tool_calls, tuple):
            raise TypeError("model response tool_calls must be a tuple")
        if not self.text.strip() and not self.tool_calls:
            raise ValueError("model response must contain text or tool_calls")


class ReferenceAgentModelPort(Protocol):
    def complete(
        self,
        state: ReferenceAgentState,
        *,
        controls: ReferenceAgentGenerationControls,
        tool_schema: JsonValue,
    ) -> ReferenceAgentModelResponse: ...


class ReferenceAgentDecisionCodec:
    """Normalize native tool calls and strict JSON envelopes into one action."""

    @staticmethod
    def _mapping(value: object, field: str) -> Mapping[str, JsonValue]:
        if not isinstance(value, Mapping):
            raise ValueError(f"model decision {field} must be an object")
        return value

    @classmethod
    def _arguments(cls, value: object) -> Mapping[str, JsonValue]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("tool call arguments are not valid JSON") from exc
        return cls._mapping(value, "arguments")

    @classmethod
    def decode(cls, response: ReferenceAgentModelResponse) -> ReferenceAgentDecision:
        if response.tool_calls:
            if len(response.tool_calls) != 1:
                raise ValueError("one agent turn must contain exactly one tool call")
            call = cls._mapping(response.tool_calls[0], "tool_call")
            function = cls._mapping(call.get("function"), "tool_call.function")
            name = function.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("tool call function name is required")
            return ReferenceAgentDecision(
                ReferenceAgentAction.from_mapping(
                    ReferenceAgentActionKind.TOOL,
                    name,
                    cls._arguments(function.get("arguments", {})),
                ),
                response.text,
            )
        try:
            raw = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "model decision must be strict JSON or a native tool call"
            ) from exc
        row = cls._mapping(raw, "root")
        if isinstance(row.get("decision"), Mapping):
            row = row["decision"]
        kind = row.get("kind", row.get("type"))
        if kind in {"tool", "function", "function_call"}:
            name, arguments = row.get("name"), row.get("arguments", {})
            if isinstance(row.get("function"), Mapping):
                function = row["function"]
                name = function.get("name", name)
                arguments = function.get("arguments", arguments)
            if not isinstance(name, str) or not name.strip():
                raise ValueError("tool decision name is required")
            return ReferenceAgentDecision(
                ReferenceAgentAction.from_mapping(
                    ReferenceAgentActionKind.TOOL,
                    name,
                    cls._arguments(arguments),
                    content=str(row.get("content", "")),
                ),
                str(row.get("reasoning", "")),
            )
        if kind in {"final", "answer"} or "answer" in row:
            content = row.get("content", row.get("answer"))
            if not isinstance(content, str) or not content.strip():
                raise ValueError("final decision content is required")
            return ReferenceAgentDecision(
                ReferenceAgentAction(
                    ReferenceAgentActionKind.FINAL, "final", content=content
                ),
                str(row.get("reasoning", "")),
            )
        if kind in {"continue", "think"}:
            content = row.get("content", row.get("reasoning", ""))
            if not isinstance(content, str) or not content.strip():
                raise ValueError("continue decision content is required")
            return ReferenceAgentDecision(
                ReferenceAgentAction(
                    ReferenceAgentActionKind.CONTINUE, "continue", content=content
                ),
                str(row.get("reasoning", "")),
            )
        raise ValueError("model decision kind is unsupported")


class ReferenceAgentDecisionAdapter(ReferenceAgentDecisionPort):
    """Connect a model port to the existing bounded ReAct method."""

    def __init__(
        self,
        model: ReferenceAgentModelPort,
        *,
        controls: ReferenceAgentGenerationControls | None = None,
        tool_registry: ToolRegistry | None = None,
        repair: Callable[
            [ReferenceAgentState, ReferenceAgentModelResponse, str],
            ReferenceAgentModelResponse,
        ] | None = None,
        max_repairs: int = 1,
    ) -> None:
        if not callable(getattr(model, "complete", None)):
            raise TypeError("model must implement complete()")
        if tool_registry is not None and type(tool_registry) is not ToolRegistry:
            raise TypeError("tool_registry must be ToolRegistry")
        if type(max_repairs) is not int or max_repairs < 0:
            raise ValueError("max_repairs must be a non-negative integer")
        self._model = model
        self._controls = controls or ReferenceAgentGenerationControls()
        self._registry = tool_registry
        self._repair = repair
        self._max_repairs = max_repairs

    def decide(self, state: ReferenceAgentState) -> ReferenceAgentDecision:
        tool_schema = () if self._registry is None else self._registry.model_tool_schema()
        response = self._model.complete(
            state, controls=self._controls, tool_schema=tool_schema
        )
        for attempt in range(self._max_repairs + 1):
            if type(response) is not ReferenceAgentModelResponse:
                raise TypeError("model must return ReferenceAgentModelResponse")
            try:
                return ReferenceAgentDecisionCodec.decode(response)
            except (TypeError, ValueError) as exc:
                if attempt >= self._max_repairs or self._repair is None:
                    raise ValueError(
                        f"model decision normalization failed: {exc}"
                    ) from exc
                response = self._repair(state, response, str(exc))
        raise AssertionError("unreachable decision adapter state")


Hook = Callable[..., None]


def _noop(*_args: object) -> None:
    return None


@dataclass(frozen=True, slots=True)
class ReferenceAgentHooks:
    before_turn: Hook = _noop
    after_decision: Hook = _noop
    before_tool: Hook = _noop
    after_tool: Hook = _noop
    after_checkpoint: Hook = _noop
    finalize: Hook = _noop

    def __post_init__(self) -> None:
        for name in (
            "before_turn", "after_decision", "before_tool",
            "after_tool", "after_checkpoint", "finalize",
        ):
            if not callable(getattr(self, name)):
                raise TypeError(f"agent hook {name} must be callable")


class _HookedPolicy:
    def __init__(self, policy: ReferenceAgentDecisionPort, hooks: ReferenceAgentHooks) -> None:
        self._policy, self._hooks = policy, hooks

    def decide(self, state: ReferenceAgentState) -> ReferenceAgentDecision:
        self._hooks.before_turn(state)
        decision = self._policy.decide(state)
        self._hooks.after_decision(state, decision)
        return decision


class _HookedTools:
    def __init__(self, tools: ReferenceAgentToolPort, hooks: ReferenceAgentHooks) -> None:
        self._tools, self._hooks = tools, hooks

    def invoke_action(self, action: ReferenceAgentAction) -> ReferenceAgentObservation:
        self._hooks.before_tool(action)
        invoke_action = getattr(self._tools, "invoke_action", None)
        observation = (
            invoke_action(action)
            if callable(invoke_action)
            else self._tools.invoke(action.name, action.arguments)
        )
        self._hooks.after_tool(action, observation)
        return observation


class _HookedProgress:
    def __init__(self, progress: ReferenceAgentProgressPort, hooks: ReferenceAgentHooks) -> None:
        self._progress, self._hooks = progress, hooks

    def checkpoint(self, state: ReferenceAgentState, *, context: ExecutionContext) -> str:
        checkpoint_id = self._progress.checkpoint(state, context=context)
        self._hooks.after_checkpoint(state, checkpoint_id)
        return checkpoint_id

    def emit(self, event: ReferenceAgentEvent, *, context: ExecutionContext) -> None:
        self._progress.emit(event, context=context)


class ReferenceAgentHarness:
    """Stable downstream entrypoint with prescribed extension nodes."""

    def __init__(
        self,
        policy: ReferenceAgentDecisionPort,
        tools: ReferenceAgentToolPort,
        *,
        progress: ReferenceAgentProgressPort | None = None,
        hooks: ReferenceAgentHooks | None = None,
    ) -> None:
        if not callable(getattr(policy, "decide", None)):
            raise TypeError("harness policy must implement decide()")
        if not callable(getattr(tools, "invoke", None)) and not callable(
            getattr(tools, "invoke_action", None)
        ):
            raise TypeError("harness tools must implement invoke() or invoke_action()")
        selected_hooks = hooks or ReferenceAgentHooks()
        self._method = ReferenceReActMethod(
            _HookedPolicy(policy, selected_hooks),
            _HookedTools(tools, selected_hooks),
            progress=_HookedProgress(
                progress or NullReferenceAgentProgress(), selected_hooks
            ),
        )
        self._hooks = selected_hooks

    def run(
        self,
        task: str,
        *,
        max_steps: int = 16,
        context: ExecutionContext | None = None,
        initial_state: ReferenceAgentState | None = None,
    ) -> ReferenceAgentRunResult:
        result = self._method.run(
            task,
            max_steps=max_steps,
            context=context,
            initial_state=initial_state,
        )
        self._hooks.finalize(result)
        return result


__all__ = [
    "ReferenceAgentDecisionAdapter",
    "ReferenceAgentDecisionCodec",
    "ReferenceAgentGenerationControls",
    "ReferenceAgentHarness",
    "ReferenceAgentHooks",
    "ReferenceAgentModelPort",
    "ReferenceAgentModelResponse",
    "ReferenceAgentOutputMode",
]

