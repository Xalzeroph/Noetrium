from __future__ import annotations

import json
from collections.abc import Mapping

from noetrium_platform.capabilities.model.serving.endpoint.api.streaming import (
    ModelStreamEvent,
    ModelStreamEventKind,
    RawServerSentEvent,
)
from noetrium_platform.foundation.kernel.kernel import canonical_bytes, thaw_json, freeze_json
from .api import ModelProviderCompletion, ModelProviderRequestPlan, ModelProviderRuntimeError


def _json_event(raw: RawServerSentEvent) -> object:
    if raw.data == b"[DONE]":
        return "[DONE]"
    try:
        return json.loads(raw.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("provider SSE event data is not valid JSON") from exc


class _BaseStreamDecoder:
    def __init__(self, *, provider_id: str, attempt_number: int = 1) -> None:
        if type(provider_id) is not str or not provider_id.strip():
            raise ValueError("stream decoder provider_id is required")
        if type(attempt_number) is not int or attempt_number <= 0:
            raise ValueError("stream decoder attempt_number must be positive")
        self.provider_id = provider_id
        self.attempt_number = attempt_number
        self._sequence = 0

    def _event(
        self,
        kind: ModelStreamEventKind,
        provider_event_type: str,
        *,
        text_delta: str = "",
        reasoning_delta: str = "",
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        tool_arguments_delta: str = "",
        usage: object | None = None,
        content: object | None = None,
        terminal: bool = False,
    ) -> ModelStreamEvent:
        self._sequence += 1
        return ModelStreamEvent(
            kind=kind,
            sequence=self._sequence,
            provider_event_type=provider_event_type,
            provider_id=self.provider_id,
            attempt_number=self.attempt_number,
            text_delta=text_delta,
            reasoning_delta=reasoning_delta,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_arguments_delta=tool_arguments_delta,
            usage=usage,
            content=content,
            terminal=terminal,
        )


class OpenAIResponsesStreamDecoder(_BaseStreamDecoder):
    def decode(self, raw: RawServerSentEvent) -> tuple[ModelStreamEvent, ...]:
        payload = _json_event(raw)
        if payload == "[DONE]":
            return (
                self._event(
                    ModelStreamEventKind.COMPLETED,
                    raw.event or "[DONE]",
                    terminal=True,
                ),
            )
        if not isinstance(payload, Mapping):
            raise ValueError("Responses stream event must be an object")
        event_type = raw.event or payload.get("type")
        if not isinstance(event_type, str) or not event_type:
            raise ValueError("Responses stream event type is required")

        if event_type == "response.output_text.delta":
            delta = payload.get("delta")
            if not isinstance(delta, str):
                raise ValueError("Responses text delta must be text")
            return (
                self._event(
                    ModelStreamEventKind.TEXT_DELTA,
                    event_type,
                    text_delta=delta,
                    content=payload,
                ),
            )
        if event_type in {
            "response.reasoning_summary_text.delta",
            "response.reasoning_text.delta",
            "response.reasoning.delta",
        }:
            delta = payload.get("delta")
            if not isinstance(delta, str):
                raise ValueError("Responses reasoning delta must be text")
            return (
                self._event(
                    ModelStreamEventKind.REASONING_DELTA,
                    event_type,
                    reasoning_delta=delta,
                    content=payload,
                ),
            )
        if event_type == "response.function_call_arguments.delta":
            delta = payload.get("delta")
            if not isinstance(delta, str):
                raise ValueError("Responses tool argument delta must be text")
            call_id = payload.get("call_id") or payload.get("item_id")
            name = payload.get("name")
            return (
                self._event(
                    ModelStreamEventKind.TOOL_CALL_DELTA,
                    event_type,
                    tool_call_id=call_id if isinstance(call_id, str) else None,
                    tool_name=name if isinstance(name, str) else None,
                    tool_arguments_delta=delta,
                    content=payload,
                ),
            )
        if event_type == "response.completed":
            response = payload.get("response")
            usage = response.get("usage") if isinstance(response, Mapping) else None
            rows: list[ModelStreamEvent] = []
            if isinstance(usage, Mapping):
                normalized = {
                    **dict(usage),
                    "prompt_tokens": usage.get("input_tokens"),
                    "completion_tokens": usage.get("output_tokens"),
                }
                rows.append(
                    self._event(
                        ModelStreamEventKind.USAGE,
                        event_type,
                        usage=normalized,
                        content=payload,
                    )
                )
            rows.append(
                self._event(
                    ModelStreamEventKind.COMPLETED,
                    event_type,
                    content=payload,
                    terminal=True,
                )
            )
            return tuple(rows)
        if event_type in {"response.failed", "error"}:
            return (
                self._event(
                    ModelStreamEventKind.ERROR,
                    event_type,
                    content=payload,
                    terminal=True,
                ),
            )
        if event_type == "response.incomplete":
            return (
                self._event(
                    ModelStreamEventKind.COMPLETED,
                    event_type,
                    content=payload,
                    terminal=True,
                ),
            )
        return (
            self._event(
                ModelStreamEventKind.CONTENT,
                event_type,
                content=payload,
            ),
        )


class OpenAIChatStreamDecoder(_BaseStreamDecoder):
    def decode(self, raw: RawServerSentEvent) -> tuple[ModelStreamEvent, ...]:
        payload = _json_event(raw)
        if payload == "[DONE]":
            return (
                self._event(
                    ModelStreamEventKind.COMPLETED,
                    raw.event or "[DONE]",
                    terminal=True,
                ),
            )
        if not isinstance(payload, Mapping):
            raise ValueError("OpenAI chat stream event must be an object")
        event_type = raw.event or "chat.completion.chunk"
        rows: list[ModelStreamEvent] = []
        choices = payload.get("choices")
        if isinstance(choices, (tuple, list)):
            for choice in choices:
                if not isinstance(choice, Mapping):
                    continue
                delta = choice.get("delta")
                if isinstance(delta, Mapping):
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        rows.append(
                            self._event(
                                ModelStreamEventKind.TEXT_DELTA,
                                event_type,
                                text_delta=content,
                                content=payload,
                            )
                        )
                    reasoning = delta.get("reasoning_content")
                    if isinstance(reasoning, str) and reasoning:
                        rows.append(
                            self._event(
                                ModelStreamEventKind.REASONING_DELTA,
                                event_type,
                                reasoning_delta=reasoning,
                                content=payload,
                            )
                        )
                    tool_calls = delta.get("tool_calls")
                    if isinstance(tool_calls, (tuple, list)):
                        for call in tool_calls:
                            if not isinstance(call, Mapping):
                                continue
                            function = call.get("function")
                            function = function if isinstance(function, Mapping) else {}
                            arguments = function.get("arguments", "")
                            rows.append(
                                self._event(
                                    ModelStreamEventKind.TOOL_CALL_DELTA,
                                    event_type,
                                    tool_call_id=call.get("id") if isinstance(call.get("id"), str) else None,
                                    tool_name=function.get("name") if isinstance(function.get("name"), str) else None,
                                    tool_arguments_delta=arguments if isinstance(arguments, str) else "",
                                    content=payload,
                                )
                            )
                finish = choice.get("finish_reason")
                if isinstance(finish, str) and finish:
                    rows.append(
                        self._event(
                            ModelStreamEventKind.COMPLETED,
                            event_type,
                            content={"finish_reason": finish},
                            terminal=True,
                        )
                    )
        usage = payload.get("usage")
        if isinstance(usage, Mapping):
            rows.append(
                self._event(
                    ModelStreamEventKind.USAGE,
                    event_type,
                    usage=usage,
                    content=payload,
                )
            )
        return tuple(rows) or (
            self._event(ModelStreamEventKind.CONTENT, event_type, content=payload),
        )


class AnthropicStreamDecoder(_BaseStreamDecoder):
    def __init__(self, *, provider_id: str, attempt_number: int = 1) -> None:
        super().__init__(provider_id=provider_id, attempt_number=attempt_number)
        self._tools: dict[int, tuple[str | None, str | None]] = {}

    def decode(self, raw: RawServerSentEvent) -> tuple[ModelStreamEvent, ...]:
        payload = _json_event(raw)
        if not isinstance(payload, Mapping):
            raise ValueError("Anthropic stream event must be an object")
        event_type = raw.event or payload.get("type")
        if not isinstance(event_type, str) or not event_type:
            raise ValueError("Anthropic stream event type is required")
        if event_type == "content_block_start":
            index = payload.get("index")
            block = payload.get("content_block")
            if isinstance(index, int) and isinstance(block, Mapping):
                if block.get("type") == "tool_use":
                    call_id = block.get("id")
                    name = block.get("name")
                    self._tools[index] = (
                        call_id if isinstance(call_id, str) else None,
                        name if isinstance(name, str) else None,
                    )
            return (
                self._event(ModelStreamEventKind.CONTENT, event_type, content=payload),
            )
        if event_type == "content_block_delta":
            index = payload.get("index")
            delta = payload.get("delta")
            if not isinstance(delta, Mapping):
                return (
                    self._event(ModelStreamEventKind.CONTENT, event_type, content=payload),
                )
            delta_type = delta.get("type")
            if delta_type == "text_delta" and isinstance(delta.get("text"), str):
                return (
                    self._event(
                        ModelStreamEventKind.TEXT_DELTA,
                        event_type,
                        text_delta=delta["text"],
                        content=payload,
                    ),
                )
            if delta_type == "thinking_delta" and isinstance(delta.get("thinking"), str):
                return (
                    self._event(
                        ModelStreamEventKind.REASONING_DELTA,
                        event_type,
                        reasoning_delta=delta["thinking"],
                        content=payload,
                    ),
                )
            if delta_type == "input_json_delta" and isinstance(delta.get("partial_json"), str):
                call_id, name = self._tools.get(index, (None, None)) if isinstance(index, int) else (None, None)
                return (
                    self._event(
                        ModelStreamEventKind.TOOL_CALL_DELTA,
                        event_type,
                        tool_call_id=call_id,
                        tool_name=name,
                        tool_arguments_delta=delta["partial_json"],
                        content=payload,
                    ),
                )
            return (
                self._event(ModelStreamEventKind.CONTENT, event_type, content=payload),
            )
        if event_type in {"message_start", "message_delta"}:
            usage = None
            if event_type == "message_start":
                message = payload.get("message")
                usage = message.get("usage") if isinstance(message, Mapping) else None
            else:
                usage = payload.get("usage")
            if isinstance(usage, Mapping):
                normalized = {
                    **dict(usage),
                    "prompt_tokens": usage.get("input_tokens"),
                    "completion_tokens": usage.get("output_tokens"),
                }
                return (
                    self._event(
                        ModelStreamEventKind.USAGE,
                        event_type,
                        usage=normalized,
                        content=payload,
                    ),
                )
        if event_type == "message_stop":
            return (
                self._event(
                    ModelStreamEventKind.COMPLETED,
                    event_type,
                    content=payload,
                    terminal=True,
                ),
            )
        if event_type == "error":
            return (
                self._event(
                    ModelStreamEventKind.ERROR,
                    event_type,
                    content=payload,
                    terminal=True,
                ),
            )
        return (
            self._event(ModelStreamEventKind.CONTENT, event_type, content=payload),
        )


class GeminiStreamDecoder(_BaseStreamDecoder):
    def decode(self, raw: RawServerSentEvent) -> tuple[ModelStreamEvent, ...]:
        payload = _json_event(raw)
        if not isinstance(payload, Mapping):
            raise ValueError("Gemini stream event must be an object")
        event_type = raw.event or "generateContent.chunk"
        rows: list[ModelStreamEvent] = []
        candidates = payload.get("candidates")
        if isinstance(candidates, (tuple, list)):
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    continue
                content = candidate.get("content")
                parts = content.get("parts") if isinstance(content, Mapping) else None
                if isinstance(parts, (tuple, list)):
                    for part in parts:
                        if not isinstance(part, Mapping):
                            continue
                        text = part.get("text")
                        if isinstance(text, str) and text:
                            rows.append(
                                self._event(
                                    ModelStreamEventKind.REASONING_DELTA if part.get("thought") is True else ModelStreamEventKind.TEXT_DELTA,
                                    event_type,
                                    reasoning_delta=text if part.get("thought") is True else "",
                                    text_delta="" if part.get("thought") is True else text,
                                    content=part,
                                )
                            )
                        function = part.get("functionCall")
                        if isinstance(function, Mapping):
                            name = function.get("name")
                            args = function.get("args", {})
                            rows.append(
                                self._event(
                                    ModelStreamEventKind.TOOL_CALL_DELTA,
                                    event_type,
                                    tool_name=name if isinstance(name, str) else None,
                                    tool_arguments_delta=json.dumps(
                                        thaw_json(freeze_json(args)),
                                        separators=(",", ":"),
                                        sort_keys=True,
                                    ) if isinstance(args, Mapping) else "",
                                    content=part,
                                )
                            )
                finish = candidate.get("finishReason")
                if isinstance(finish, str) and finish:
                    rows.append(
                        self._event(
                            ModelStreamEventKind.COMPLETED,
                            event_type,
                            content={"finish_reason": finish},
                            terminal=True,
                        )
                    )
        usage = payload.get("usageMetadata")
        if isinstance(usage, Mapping):
            normalized = {
                **dict(usage),
                "prompt_tokens": usage.get("promptTokenCount"),
                "completion_tokens": usage.get("candidatesTokenCount"),
                "total_tokens": usage.get("totalTokenCount"),
            }
            rows.append(
                self._event(
                    ModelStreamEventKind.USAGE,
                    event_type,
                    usage=normalized,
                    content=payload,
                )
            )
        return tuple(rows) or (
            self._event(ModelStreamEventKind.CONTENT, event_type, content=payload),
        )




class ModelStreamAccumulator:
    """Reconstruct one canonical completion from canonical stream events."""

    def __init__(self, plan: ModelProviderRequestPlan) -> None:
        if not isinstance(plan, ModelProviderRequestPlan):
            raise TypeError("stream accumulator requires ModelProviderRequestPlan")
        self._plan = plan
        self._text: list[str] = []
        self._reasoning: list[str] = []
        self._usage: Mapping[str, object] | None = None
        self._terminal_content: object | None = None
        self._finish_reason: str | None = None
        self._tool_rows: dict[str, dict[str, object]] = {}
        self._tool_order: list[str] = []
        self._anonymous_tool_counter = 0
        self._last_tool_key: str | None = None
        self._terminal_seen = False
        self._terminal_error = False

    def add(self, event: ModelStreamEvent) -> None:
        if not isinstance(event, ModelStreamEvent):
            raise TypeError("stream accumulator requires ModelStreamEvent")
        if event.text_delta:
            self._text.append(event.text_delta)
        if event.reasoning_delta:
            self._reasoning.append(event.reasoning_delta)
        if event.usage is not None:
            self._usage = event.usage
        if event.kind is ModelStreamEventKind.TOOL_CALL_DELTA:
            key = event.tool_call_id
            if key is None:
                if event.tool_name is not None:
                    key = f"name:{event.tool_name}"
                elif self._last_tool_key is not None:
                    key = self._last_tool_key
                else:
                    self._anonymous_tool_counter += 1
                    key = f"anonymous:{self._anonymous_tool_counter}"
            row = self._tool_rows.get(key)
            if row is None:
                row = {
                    "id": event.tool_call_id or key,
                    "name": event.tool_name,
                    "arguments": [],
                }
                self._tool_rows[key] = row
                self._tool_order.append(key)
            if event.tool_name is not None:
                row["name"] = event.tool_name
            if event.tool_call_id is not None:
                row["id"] = event.tool_call_id
            row["arguments"].append(event.tool_arguments_delta)
            self._last_tool_key = key
        if event.terminal:
            self._terminal_seen = True
            self._terminal_error = event.kind is ModelStreamEventKind.ERROR
            self._terminal_content = event.content
            if isinstance(event.content, Mapping):
                finish = event.content.get("finish_reason")
                if isinstance(finish, str):
                    self._finish_reason = finish
                response = event.content.get("response")
                if isinstance(response, Mapping):
                    status = response.get("status")
                    if isinstance(status, str):
                        self._finish_reason = "stop" if status == "completed" else status
            if self._finish_reason is None:
                self._finish_reason = (
                    "stop"
                    if event.kind is ModelStreamEventKind.COMPLETED
                    else "error"
                )

    def completion(self, *, response_bytes: bytes) -> ModelProviderCompletion:
        if type(response_bytes) is not bytes:
            raise TypeError("stream accumulator response_bytes must be exact bytes")
        if not self._terminal_seen:
            raise ModelProviderRuntimeError(
                "provider stream ended without canonical terminal event"
            )
        if self._terminal_error:
            raise ModelProviderRuntimeError(
                "provider stream terminated with error event"
            )
        tool_calls: list[dict[str, object]] = []
        for key in self._tool_order:
            row = self._tool_rows[key]
            name = row.get("name")
            if not isinstance(name, str) or not name:
                raise ModelProviderRuntimeError(
                    "stream ended with tool call missing function name"
                )
            raw_arguments = "".join(row["arguments"])
            if raw_arguments:
                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError as exc:
                    raise ModelProviderRuntimeError(
                        "stream ended with incomplete tool-call JSON"
                    ) from exc
            else:
                arguments = {}
            if not isinstance(arguments, Mapping):
                raise ModelProviderRuntimeError(
                    "stream tool-call arguments must decode to an object"
                )
            tool_calls.append(
                {
                    "id": row["id"],
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": dict(arguments),
                    },
                }
            )

        content_blocks: list[dict[str, object]] = []
        reasoning = "".join(self._reasoning)
        text = "".join(self._text)
        if reasoning:
            content_blocks.append(
                {
                    "kind": "reasoning",
                    "provider_id": self._plan.profile.provider_id,
                    "provider_payload": {"streamed": True},
                    "text": reasoning,
                }
            )
        if text:
            content_blocks.append(
                {
                    "kind": "text",
                    "provider_id": self._plan.profile.provider_id,
                    "provider_payload": {"streamed": True},
                    "text": text,
                }
            )
        for call in tool_calls:
            content_blocks.append(
                {
                    "kind": "tool_call",
                    "provider_id": self._plan.profile.provider_id,
                    "provider_payload": {"streamed": True},
                    "tool_call": call,
                }
            )
        if not content_blocks and self._terminal_content is not None:
            content_blocks.append(
                {
                    "kind": "provider_content",
                    "provider_id": self._plan.profile.provider_id,
                    "provider_payload": thaw_json(
                        freeze_json(self._terminal_content)
                    ),
                }
            )
        provider_response = {
            "stream": True,
            "terminal": thaw_json(freeze_json(self._terminal_content))
            if self._terminal_content is not None
            else None,
        }
        return ModelProviderCompletion(
            text=text,
            tool_calls=tuple(tool_calls),
            finish_reason=self._finish_reason,
            usage=None if self._usage is None else dict(self._usage),
            provider_response=provider_response,
            provider_id=self._plan.profile.provider_id,
            plan_digest=self._plan.plan_digest,
            response_bytes=response_bytes,
            content_blocks=tuple(content_blocks),
        )


def stream_decoder_for_protocol(
    protocol_id: str,
    *,
    provider_id: str,
    attempt_number: int = 1,
):
    if protocol_id == "openai.responses":
        return OpenAIResponsesStreamDecoder(provider_id=provider_id, attempt_number=attempt_number)
    if protocol_id == "openai.chat-completions":
        return OpenAIChatStreamDecoder(provider_id=provider_id, attempt_number=attempt_number)
    if protocol_id == "anthropic.messages":
        return AnthropicStreamDecoder(provider_id=provider_id, attempt_number=attempt_number)
    if protocol_id == "google.generate-content":
        return GeminiStreamDecoder(provider_id=provider_id, attempt_number=attempt_number)
    raise ValueError(f"provider protocol has no stream decoder: {protocol_id}")


__all__ = [
    "AnthropicStreamDecoder",
    "GeminiStreamDecoder",
    "OpenAIChatStreamDecoder",
    "OpenAIResponsesStreamDecoder",
    "ModelStreamAccumulator",
    "stream_decoder_for_protocol",
]
