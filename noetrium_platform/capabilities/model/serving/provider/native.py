from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256

from noetrium_platform.foundation.kernel.kernel import (
    JsonInput,
    JsonObject,
    JsonValue,
    canonical_bytes,
    canonical_digest,
    freeze_json,
    thaw_json,
)

from .api import (
    ModelProviderCompletion,
    ModelProviderRequestPlan,
    ModelProviderRequestUnsupported,
    ModelProviderRuntimeError,
    ModelProviderRuntimeProfile,
)


_OPENAI_CHAT_PARAMETERS = (
    "frequency_penalty",
    "logit_bias",
    "logprobs",
    "top_logprobs",
    "max_tokens",
    "max_completion_tokens",
    "n",
    "presence_penalty",
    "response_format",
    "seed",
    "stop",
    "stream",
    "stream_options",
    "temperature",
    "top_p",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "user",
    "reasoning_effort",
    "service_tier",
    "store",
)

_OPENAI_RESPONSES_PARAMETERS = (
    "max_tokens",
    "max_completion_tokens",
    "response_format",
    "stream",
    "temperature",
    "top_p",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "reasoning_effort",
    "service_tier",
    "store",
    "metadata",
    "previous_response_id",
    "include",
    "background",
    "prompt_cache_key",
    "prompt_cache_retention",
)

_VLLM_EXTENSIONS = (
    "chat_template_kwargs",
    "thinking_token_budget",
    "include_reasoning",
    "top_k",
    "min_p",
    "repetition_penalty",
    "stop_token_ids",
    "ignore_eos",
    "include_stop_str_in_output",
    "use_beam_search",
    "length_penalty",
)

_SGLANG_EXTENSIONS = (
    "chat_template_kwargs",
    "top_k",
    "min_p",
    "repetition_penalty",
)

_ANTHROPIC_PARAMETERS = (
    "max_tokens",
    "max_completion_tokens",
    "temperature",
    "top_p",
    "top_k",
    "stop",
    "tools",
    "tool_choice",
    "thinking",
    "metadata",
    "service_tier",
    "stream",
)

_GEMINI_PARAMETERS = (
    "max_tokens",
    "max_completion_tokens",
    "temperature",
    "top_p",
    "top_k",
    "stop",
    "response_format",
    "seed",
    "tools",
    "tool_choice",
    "stream",
)


@dataclass(frozen=True, slots=True)
class NativeModelProviderSpec:
    provider_id: str
    protocol_id: str
    engine_aliases: tuple[str, ...]
    supported_parameters: tuple[str, ...]
    passthrough_parameters: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    auth_kind: str = "bearer-optional"
    spec_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("provider_id", "protocol_id", "auth_kind"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"native model provider {name} is required")
        for name in (
            "engine_aliases",
            "supported_parameters",
            "passthrough_parameters",
            "features",
        ):
            values = getattr(self, name)
            if type(values) is not tuple or any(
                type(value) is not str or not value.strip() for value in values
            ):
                raise TypeError(f"native model provider {name} must be a text tuple")
            object.__setattr__(
                self,
                name,
                tuple(sorted({value.strip().lower() if name == "engine_aliases" else value for value in values})),
            )
        if set(self.supported_parameters) & set(self.passthrough_parameters):
            raise ValueError("native provider standard/passthrough parameters overlap")
        object.__setattr__(
            self,
            "spec_digest",
            canonical_digest(
                {
                    "schema": "noetrium.native-model-provider-spec.v1",
                    "provider_id": self.provider_id,
                    "protocol_id": self.protocol_id,
                    "engine_aliases": self.engine_aliases,
                    "supported_parameters": self.supported_parameters,
                    "passthrough_parameters": self.passthrough_parameters,
                    "features": self.features,
                    "auth_kind": self.auth_kind,
                }
            ),
        )


def _features(
    parameters: tuple[str, ...],
    *,
    multimodal: bool = False,
    reasoning: bool = False,
) -> tuple[str, ...]:
    params = set(parameters)
    values = {"generation"}
    if "seed" in params:
        values.add("seeded_sampling")
    if "response_format" in params:
        values.add("structured_output")
    if "tools" in params:
        values.add("tools")
    if "parallel_tool_calls" in params:
        values.add("parallel_tools")
    if "stream" in params:
        values.add("streaming")
    if reasoning or params & {"reasoning_effort", "thinking", "thinking_token_budget"}:
        values.add("reasoning")
    if multimodal:
        values.add("multimodal")
    return tuple(sorted(values))


def _openai_spec(
    provider_id: str,
    aliases: tuple[str, ...],
    *,
    passthrough: tuple[str, ...] = (),
    auth_kind: str = "bearer-optional",
    reasoning: bool = True,
    multimodal: bool = True,
) -> NativeModelProviderSpec:
    return NativeModelProviderSpec(
        provider_id=provider_id,
        protocol_id="openai.chat-completions",
        engine_aliases=aliases,
        supported_parameters=_OPENAI_CHAT_PARAMETERS,
        passthrough_parameters=passthrough,
        features=_features(
            _OPENAI_CHAT_PARAMETERS,
            reasoning=reasoning,
            multimodal=multimodal,
        ),
        auth_kind=auth_kind,
    )


_NATIVE_PROVIDER_SPECS = (
    _openai_spec("vllm", ("vllm", "hosted_vllm"), passthrough=_VLLM_EXTENSIONS),
    _openai_spec("sglang", ("sglang",), passthrough=_SGLANG_EXTENSIONS),
    _openai_spec("openai", ("openai", "openai-compatible", "openai_compatible")),
    _openai_spec("azure", ("azure", "azure-openai", "azure_openai"), auth_kind="api-key"),
    _openai_spec("deepseek", ("deepseek",)),
    _openai_spec("moonshot", ("moonshot", "kimi")),
    _openai_spec("mistral", ("mistral",)),
    _openai_spec("groq", ("groq",)),
    _openai_spec("together", ("together",)),
    _openai_spec("fireworks", ("fireworks", "fireworks-ai")),
    _openai_spec("xai", ("xai", "grok")),
    _openai_spec("openrouter", ("openrouter",)),
    _openai_spec("perplexity", ("perplexity",)),
    _openai_spec("sambanova", ("sambanova",)),
    _openai_spec("ollama", ("ollama",), auth_kind="none"),
    _openai_spec("hf-inference", ("hf", "huggingface", "hf-inference", "hf_inference")),
    NativeModelProviderSpec(
        provider_id="anthropic",
        protocol_id="anthropic.messages",
        engine_aliases=("anthropic", "claude"),
        supported_parameters=_ANTHROPIC_PARAMETERS,
        features=_features(
            _ANTHROPIC_PARAMETERS,
            reasoning=True,
            multimodal=True,
        ),
        auth_kind="anthropic",
    ),
    NativeModelProviderSpec(
        provider_id="gemini",
        protocol_id="google.generate-content",
        engine_aliases=("gemini", "google", "google-genai"),
        supported_parameters=_GEMINI_PARAMETERS,
        features=_features(
            _GEMINI_PARAMETERS,
            reasoning=True,
            multimodal=True,
        ),
        auth_kind="google-api-key",
    ),
    NativeModelProviderSpec(
        provider_id="vertex-ai",
        protocol_id="google.generate-content",
        engine_aliases=("vertex", "vertex-ai", "vertex_ai"),
        supported_parameters=_GEMINI_PARAMETERS,
        features=_features(
            _GEMINI_PARAMETERS,
            reasoning=True,
            multimodal=True,
        ),
        auth_kind="bearer",
    ),
)


class NativeModelProviderCatalog:
    def __init__(
        self,
        specs: tuple[NativeModelProviderSpec, ...] = _NATIVE_PROVIDER_SPECS,
    ) -> None:
        if type(specs) is not tuple or not specs:
            raise TypeError("native model provider catalog requires a non-empty spec tuple")
        by_id: dict[str, NativeModelProviderSpec] = {}
        by_engine: dict[str, NativeModelProviderSpec] = {}
        for spec in specs:
            if not isinstance(spec, NativeModelProviderSpec):
                raise TypeError("native model provider catalog contains invalid spec")
            if spec.provider_id in by_id:
                raise ValueError(f"duplicate native provider id: {spec.provider_id}")
            by_id[spec.provider_id] = spec
            for alias in spec.engine_aliases:
                if alias in by_engine:
                    raise ValueError(f"duplicate native provider engine alias: {alias}")
                by_engine[alias] = spec
        self._by_id = by_id
        self._by_engine = by_engine
        self.catalog_digest = canonical_digest(
            {
                "schema": "noetrium.native-model-provider-catalog.v1",
                "specs": tuple(spec.spec_digest for spec in specs),
            }
        )

    def resolve(
        self,
        *,
        model_engine: str,
        provider_id: str | None = None,
    ) -> NativeModelProviderSpec:
        if type(model_engine) is not str or not model_engine.strip():
            raise ValueError("model engine is required for native provider resolution")
        if provider_id is not None:
            if type(provider_id) is not str or not provider_id.strip():
                raise ValueError("provider_id must be non-empty text")
            spec = self._by_id.get(provider_id.strip().lower())
            if spec is None:
                raise ModelProviderRequestUnsupported(
                    f"native model provider is not registered: {provider_id}"
                )
            return spec
        normalized = model_engine.strip().lower()
        spec = self._by_engine.get(normalized)
        if spec is None:
            raise ModelProviderRequestUnsupported(
                f"model engine has no native provider protocol: {model_engine}"
            )
        return spec


def provider_profile_for_protocol(
    profile: ModelProviderRuntimeProfile,
    protocol_id: str,
) -> ModelProviderRuntimeProfile:
    if not isinstance(profile, ModelProviderRuntimeProfile):
        raise TypeError("provider protocol override requires runtime profile")
    if type(protocol_id) is not str or not protocol_id.strip():
        raise ValueError("provider protocol override requires protocol_id")
    if protocol_id == profile.protocol_id:
        return profile
    if protocol_id != "openai.responses":
        raise ModelProviderRequestUnsupported(
            f"provider protocol override is unsupported: {protocol_id}"
        )
    if profile.provider_id not in {
        "openai",
        "azure",
        "vllm",
        "sglang",
        "openai-compatible",
    }:
        raise ModelProviderRequestUnsupported(
            f"provider does not support OpenAI Responses protocol: {profile.provider_id}"
        )
    return ModelProviderRuntimeProfile(
        provider_id=profile.provider_id,
        logical_model_name=profile.logical_model_name,
        provider_model_name=profile.provider_model_name,
        supported_parameters=_OPENAI_RESPONSES_PARAMETERS,
        passthrough_parameters=profile.passthrough_parameters,
        features=tuple(sorted(set(profile.features) | {"reasoning", "tools"})),
        protocol_id="openai.responses",
        auth_kind=profile.auth_kind,
    )


class NativeModelProviderProfileResolver:
    def __init__(self, catalog: NativeModelProviderCatalog | None = None) -> None:
        self.catalog = catalog or NativeModelProviderCatalog()

    def resolve(
        self,
        *,
        logical_model_name: str,
        provider_model_name: str,
        model_engine: str,
        provider_id: str | None = None,
    ) -> ModelProviderRuntimeProfile:
        spec = self.catalog.resolve(
            model_engine=model_engine,
            provider_id=provider_id,
        )
        return ModelProviderRuntimeProfile(
            provider_id=spec.provider_id,
            logical_model_name=logical_model_name,
            provider_model_name=provider_model_name,
            supported_parameters=spec.supported_parameters,
            passthrough_parameters=spec.passthrough_parameters,
            features=spec.features,
            protocol_id=spec.protocol_id,
            auth_kind=spec.auth_kind,
        )


@dataclass(frozen=True, slots=True)
class ModelProviderWirePlan:
    plan: ModelProviderRequestPlan
    body: JsonObject
    headers: tuple[tuple[str, str], ...] = field(repr=False, compare=False)
    wire_bytes: bytes
    wire_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.plan, ModelProviderRequestPlan):
            raise TypeError("provider wire plan requires ModelProviderRequestPlan")
        if not isinstance(self.body, Mapping):
            raise TypeError("provider wire body must be a mapping")
        object.__setattr__(self, "body", freeze_json(self.body))
        if type(self.headers) is not tuple or any(
            type(row) is not tuple
            or len(row) != 2
            or any(type(value) is not str or not value for value in row)
            for row in self.headers
        ):
            raise TypeError("provider wire headers must be text pairs")
        if type(self.wire_bytes) is not bytes:
            raise TypeError("provider wire bytes must be exact bytes")
        object.__setattr__(
            self,
            "wire_digest",
            canonical_digest(
                {
                    "schema": "noetrium.model-provider-wire-plan.v1",
                    "plan_digest": self.plan.plan_digest,
                    "protocol_id": self.plan.profile.protocol_id,
                    "headers": tuple(name.lower() for name, _ in self.headers),
                    "wire_sha256": sha256(self.wire_bytes).hexdigest(),
                }
            ),
        )


def _error_detail(value: object) -> str:
    if isinstance(value, Mapping):
        for key in ("message", "detail", "error_description"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()[:1024]
        error = value.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()[:1024]
        if isinstance(error, Mapping):
            nested = _error_detail(error)
            if nested:
                return nested
    if isinstance(value, (tuple, list)):
        for item in value:
            nested = _error_detail(item)
            if nested:
                return nested
    return ""


def provider_error_detail(value: object) -> str:
    detail = _error_detail(value)
    return detail or f"provider_response_sha256={sha256(canonical_bytes(value)).hexdigest()}"


def _message_content(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (tuple, list)):
        texts: list[str] = []
        for part in value:
            if isinstance(part, Mapping):
                if part.get("type") in {"text", "input_text", "output_text"}:
                    text = part.get("text")
                    if isinstance(text, str):
                        texts.append(text)
            elif isinstance(part, str):
                texts.append(part)
        return "".join(texts)
    return ""


def _canonical_content_block(
    *,
    kind: str,
    provider_id: str,
    provider_payload: object,
    **fields: JsonInput,
) -> dict[str, object]:
    if type(kind) is not str or not kind.strip():
        raise ValueError("canonical model content kind is required")
    if type(provider_id) is not str or not provider_id.strip():
        raise ValueError("canonical model content provider_id is required")
    return {
        "kind": kind,
        "provider_id": provider_id,
        "provider_payload": thaw_json(freeze_json(provider_payload)),
        **{key: thaw_json(freeze_json(value)) for key, value in fields.items()},
    }


def _openai_content_blocks(
    provider_id: str,
    message: Mapping[str, object],
    tool_calls: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    content = message.get("content")
    if isinstance(content, str):
        if content:
            rows.append(_canonical_content_block(
                kind="text",
                provider_id=provider_id,
                provider_payload=content,
                text=content,
            ))
    elif isinstance(content, (tuple, list)):
        for part in content:
            if isinstance(part, Mapping):
                part_type = part.get("type")
                text = part.get("text")
                if part_type in {"text", "input_text", "output_text"} and isinstance(text, str):
                    rows.append(_canonical_content_block(
                        kind="text",
                        provider_id=provider_id,
                        provider_payload=part,
                        text=text,
                    ))
                else:
                    rows.append(_canonical_content_block(
                        kind="provider_content",
                        provider_id=provider_id,
                        provider_payload=part,
                    ))
            elif isinstance(part, str):
                rows.append(_canonical_content_block(
                    kind="text",
                    provider_id=provider_id,
                    provider_payload=part,
                    text=part,
                ))
    reasoning = message.get("reasoning_content")
    if reasoning is not None:
        fields: dict[str, JsonInput] = {}
        if isinstance(reasoning, str):
            fields["text"] = reasoning
        rows.append(_canonical_content_block(
            kind="reasoning",
            provider_id=provider_id,
            provider_payload={"reasoning_content": thaw_json(freeze_json(reasoning))},
            **fields,
        ))
    refusal = message.get("refusal")
    if isinstance(refusal, str) and refusal:
        rows.append(_canonical_content_block(
            kind="refusal",
            provider_id=provider_id,
            provider_payload={"refusal": refusal},
            text=refusal,
        ))
    raw_calls = message.get("tool_calls")
    if isinstance(raw_calls, (tuple, list)):
        for index, call in enumerate(tool_calls):
            raw = raw_calls[index] if index < len(raw_calls) else call
            rows.append(_canonical_content_block(
                kind="tool_call",
                provider_id=provider_id,
                provider_payload=raw,
                tool_call=call,
            ))
    return tuple(rows)


def _canonical_tool_calls(raw_calls: object) -> tuple[dict[str, object], ...]:
    if raw_calls in (None, (), []):
        return ()
    if not isinstance(raw_calls, (tuple, list)):
        raise ModelProviderRuntimeError("provider tool_calls must be an array")
    rows: list[dict[str, object]] = []
    for raw in raw_calls:
        if not isinstance(raw, Mapping):
            raise ModelProviderRuntimeError("provider tool_call must be an object")
        call_id = raw.get("id")
        function = raw.get("function")
        if not isinstance(call_id, str) or not call_id:
            raise ModelProviderRuntimeError("provider tool_call id is invalid")
        if not isinstance(function, Mapping):
            raise ModelProviderRuntimeError("provider tool_call function is invalid")
        name = function.get("name")
        arguments = function.get("arguments", {})
        if not isinstance(name, str) or not name:
            raise ModelProviderRuntimeError("provider tool_call function name is invalid")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ModelProviderRuntimeError(
                    "provider tool_call arguments are invalid JSON"
                ) from exc
        if not isinstance(arguments, Mapping):
            raise ModelProviderRuntimeError(
                "provider tool_call arguments must normalize to an object"
            )
        rows.append(
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": dict(arguments),
                },
            }
        )
    return tuple(rows)


def _message_content_blocks(message: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    value = message.get("content_blocks")
    if value is None:
        return ()
    if not isinstance(value, (tuple, list)):
        raise ModelProviderRequestUnsupported(
            "canonical message content_blocks must be an array"
        )
    rows: list[Mapping[str, object]] = []
    for block in value:
        if not isinstance(block, Mapping):
            raise ModelProviderRequestUnsupported(
                "canonical message content block must be an object"
            )
        kind = block.get("kind")
        provider_id = block.get("provider_id")
        if type(kind) is not str or not kind.strip():
            raise ModelProviderRequestUnsupported(
                "canonical message content block kind is required"
            )
        if type(provider_id) is not str or not provider_id.strip():
            raise ModelProviderRequestUnsupported(
                "canonical message content block provider_id is required"
            )
        if "provider_payload" not in block:
            raise ModelProviderRequestUnsupported(
                "canonical message content block requires provider_payload"
            )
        rows.append(block)
    return tuple(rows)


def _cross_provider_opaque_state_error(
    *,
    target_provider_id: str,
    block: Mapping[str, object],
) -> ModelProviderRequestUnsupported:
    return ModelProviderRequestUnsupported(
        "opaque provider state cannot cross provider boundary: "
        f"source={block.get('provider_id')}; "
        f"target={target_provider_id}; "
        f"kind={block.get('kind')}"
    )


def _openai_wire_tool_call(call: Mapping[str, object]) -> dict[str, object]:
    call_id = call.get("id")
    function = call.get("function")
    if type(call_id) is not str or not call_id:
        raise ModelProviderRequestUnsupported(
            "canonical tool_call id is required for OpenAI replay"
        )
    if not isinstance(function, Mapping):
        raise ModelProviderRequestUnsupported(
            "canonical tool_call function is required for OpenAI replay"
        )
    name = function.get("name")
    arguments = function.get("arguments", {})
    if type(name) is not str or not name:
        raise ModelProviderRequestUnsupported(
            "canonical tool_call function name is required for OpenAI replay"
        )
    if not isinstance(arguments, Mapping):
        raise ModelProviderRequestUnsupported(
            "canonical tool_call arguments must be an object for OpenAI replay"
        )
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(
                thaw_json(freeze_json(arguments)),
                separators=(",", ":"),
                sort_keys=True,
                ensure_ascii=False,
            ),
        },
    }


def _openai_message_from_canonical(
    message: Mapping[str, object],
    *,
    provider_id: str,
) -> dict[str, object]:
    blocks = _message_content_blocks(message)
    if not blocks:
        return thaw_json(freeze_json(message))

    role = message.get("role")
    if type(role) is not str or not role:
        raise ModelProviderRequestUnsupported(
            "canonical message role is required for OpenAI replay"
        )
    result: dict[str, object] = {"role": role}
    text_parts: list[object] = []
    tool_calls: list[object] = []
    reasoning_set = False
    refusal_set = False

    for block in blocks:
        kind = block["kind"]
        source_provider = block["provider_id"]
        payload = thaw_json(freeze_json(block["provider_payload"]))
        same_provider = source_provider == provider_id

        if kind == "text":
            if same_provider:
                text_parts.append(payload)
            else:
                text = block.get("text")
                if not isinstance(text, str):
                    raise _cross_provider_opaque_state_error(
                        target_provider_id=provider_id,
                        block=block,
                    )
                text_parts.append(text)
            continue

        if kind == "tool_call":
            if same_provider and isinstance(payload, Mapping):
                tool_calls.append(dict(payload))
            else:
                call = block.get("tool_call")
                if not isinstance(call, Mapping):
                    raise _cross_provider_opaque_state_error(
                        target_provider_id=provider_id,
                        block=block,
                    )
                tool_calls.append(_openai_wire_tool_call(call))
            continue

        if kind == "reasoning":
            if not same_provider or not isinstance(payload, Mapping):
                raise _cross_provider_opaque_state_error(
                    target_provider_id=provider_id,
                    block=block,
                )
            if "reasoning_content" not in payload:
                raise ModelProviderRequestUnsupported(
                    "OpenAI-compatible reasoning replay requires reasoning_content"
                )
            if reasoning_set:
                raise ModelProviderRequestUnsupported(
                    "OpenAI-compatible message contains multiple reasoning states"
                )
            result["reasoning_content"] = payload["reasoning_content"]
            reasoning_set = True
            continue

        if kind == "refusal":
            if same_provider and isinstance(payload, Mapping) and isinstance(
                payload.get("refusal"), str
            ):
                result["refusal"] = payload["refusal"]
            else:
                refusal = block.get("text")
                if not isinstance(refusal, str):
                    raise _cross_provider_opaque_state_error(
                        target_provider_id=provider_id,
                        block=block,
                    )
                result["refusal"] = refusal
            refusal_set = True
            continue

        if kind in {"redacted_reasoning", "provider_content", "media"}:
            if not same_provider:
                raise _cross_provider_opaque_state_error(
                    target_provider_id=provider_id,
                    block=block,
                )
            if kind == "provider_content":
                text_parts.append(payload)
                continue
            raise ModelProviderRequestUnsupported(
                f"OpenAI chat replay does not support canonical block kind: {kind}"
            )

        raise ModelProviderRequestUnsupported(
            f"OpenAI chat replay does not support canonical block kind: {kind}"
        )

    if text_parts:
        if len(text_parts) == 1 and isinstance(text_parts[0], str):
            result["content"] = text_parts[0]
        else:
            normalized_parts: list[object] = []
            for part in text_parts:
                if isinstance(part, str):
                    normalized_parts.append({"type": "text", "text": part})
                else:
                    normalized_parts.append(part)
            result["content"] = normalized_parts
    elif role == "assistant":
        result["content"] = None
    if tool_calls:
        result["tool_calls"] = tool_calls

    for key in ("name", "tool_call_id"):
        value = message.get(key)
        if value is not None:
            result[key] = thaw_json(freeze_json(value))
    return result


def _anthropic_blocks_from_canonical(
    message: Mapping[str, object],
    *,
    provider_id: str,
) -> list[object]:
    blocks = _message_content_blocks(message)
    if not blocks:
        return []
    result: list[object] = []
    for block in blocks:
        kind = block["kind"]
        source_provider = block["provider_id"]
        payload = thaw_json(freeze_json(block["provider_payload"]))
        same_provider = source_provider == provider_id
        if same_provider:
            if not isinstance(payload, Mapping):
                if kind == "text" and isinstance(payload, str):
                    result.append({"type": "text", "text": payload})
                    continue
                raise ModelProviderRequestUnsupported(
                    "Anthropic replay requires object provider_payload blocks"
                )
            result.append(dict(payload))
            continue
        if kind == "text":
            text = block.get("text")
            if not isinstance(text, str):
                raise _cross_provider_opaque_state_error(
                    target_provider_id=provider_id,
                    block=block,
                )
            result.append({"type": "text", "text": text})
            continue
        if kind == "tool_call":
            call = block.get("tool_call")
            if not isinstance(call, Mapping):
                raise _cross_provider_opaque_state_error(
                    target_provider_id=provider_id,
                    block=block,
                )
            function = call.get("function")
            if not isinstance(function, Mapping):
                raise ModelProviderRequestUnsupported(
                    "canonical tool_call function is required for Anthropic replay"
                )
            call_id = call.get("id")
            name = function.get("name")
            arguments = function.get("arguments", {})
            if (
                type(call_id) is not str
                or not call_id
                or type(name) is not str
                or not name
                or not isinstance(arguments, Mapping)
            ):
                raise ModelProviderRequestUnsupported(
                    "canonical tool_call is malformed for Anthropic replay"
                )
            result.append(
                {
                    "type": "tool_use",
                    "id": call_id,
                    "name": name,
                    "input": thaw_json(freeze_json(arguments)),
                }
            )
            continue
        raise _cross_provider_opaque_state_error(
            target_provider_id=provider_id,
            block=block,
        )
    return result


def _google_parts_from_canonical(
    message: Mapping[str, object],
    *,
    provider_id: str,
) -> list[object]:
    blocks = _message_content_blocks(message)
    if not blocks:
        return []
    result: list[object] = []
    for block in blocks:
        kind = block["kind"]
        source_provider = block["provider_id"]
        payload = thaw_json(freeze_json(block["provider_payload"]))
        same_provider = source_provider == provider_id
        if same_provider:
            if not isinstance(payload, Mapping):
                if kind == "text" and isinstance(payload, str):
                    result.append({"text": payload})
                    continue
                raise ModelProviderRequestUnsupported(
                    "Gemini replay requires object provider_payload parts"
                )
            result.append(dict(payload))
            continue
        if kind == "text":
            text = block.get("text")
            if not isinstance(text, str):
                raise _cross_provider_opaque_state_error(
                    target_provider_id=provider_id,
                    block=block,
                )
            result.append({"text": text})
            continue
        if kind == "tool_call":
            call = block.get("tool_call")
            if not isinstance(call, Mapping):
                raise _cross_provider_opaque_state_error(
                    target_provider_id=provider_id,
                    block=block,
                )
            function = call.get("function")
            if not isinstance(function, Mapping):
                raise ModelProviderRequestUnsupported(
                    "canonical tool_call function is required for Gemini replay"
                )
            name = function.get("name")
            arguments = function.get("arguments", {})
            if (
                type(name) is not str
                or not name
                or not isinstance(arguments, Mapping)
            ):
                raise ModelProviderRequestUnsupported(
                    "canonical tool_call is malformed for Gemini replay"
                )
            result.append(
                {
                    "functionCall": {
                        "name": name,
                        "args": thaw_json(freeze_json(arguments)),
                    }
                }
            )
            continue
        raise _cross_provider_opaque_state_error(
            target_provider_id=provider_id,
            block=block,
        )
    return result


class OpenAIChatProtocol:
    protocol_id = "openai.chat-completions"

    @staticmethod
    def _headers(plan: ModelProviderRequestPlan, api_key: str) -> tuple[tuple[str, str], ...]:
        provider = plan.profile.provider_id
        if not api_key:
            return ()
        if provider == "azure":
            return (("api-key", api_key),)
        return (("Authorization", f"Bearer {api_key}"),)

    def encode(
        self,
        plan: ModelProviderRequestPlan,
        *,
        api_key: str = "",
    ) -> ModelProviderWirePlan:
        if plan.profile.protocol_id != self.protocol_id:
            raise ValueError("OpenAI protocol cannot encode a different provider protocol")
        standard = dict(thaw_json(plan.standard_body))
        raw_messages = standard.get("messages")
        if not isinstance(raw_messages, list):
            raise ModelProviderRequestUnsupported(
                "OpenAI-compatible messages must be an array"
            )
        standard["messages"] = [
            _openai_message_from_canonical(
                message,
                provider_id=plan.profile.provider_id,
            )
            if isinstance(message, Mapping)
            else (_ for _ in ()).throw(
                ModelProviderRequestUnsupported(
                    "canonical message must be an object"
                )
            )
            for message in raw_messages
        ]
        body = {
            "model": plan.backend_model,
            **standard,
            **dict(thaw_json(plan.extra_body)),
        }
        raw = canonical_bytes(body)
        return ModelProviderWirePlan(
            plan=plan,
            body=body,
            headers=self._headers(plan, api_key),
            wire_bytes=raw,
        )

    def decode(
        self,
        plan: ModelProviderRequestPlan,
        payload: object,
        *,
        raw_body: bytes | None = None,
    ) -> ModelProviderCompletion:
        if not isinstance(payload, Mapping):
            raise ModelProviderRuntimeError("OpenAI-compatible response must be an object")
        choices = payload.get("choices")
        if not isinstance(choices, (tuple, list)) or len(choices) != 1:
            raise ModelProviderRuntimeError(
                "OpenAI-compatible response must contain exactly one choice"
            )
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise ModelProviderRuntimeError("OpenAI-compatible choice must be an object")
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise ModelProviderRuntimeError(
                "OpenAI-compatible choice must contain a message object"
            )
        text = _message_content(message.get("content"))
        tool_calls = _canonical_tool_calls(message.get("tool_calls"))
        content_blocks = _openai_content_blocks(
            plan.profile.provider_id,
            message,
            tool_calls,
        )
        usage = payload.get("usage")
        if usage is not None and not isinstance(usage, Mapping):
            raise ModelProviderRuntimeError("OpenAI-compatible usage must be an object")
        response_bytes = raw_body if raw_body is not None else canonical_bytes(payload)
        return ModelProviderCompletion(
            text=text,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason") if isinstance(choice.get("finish_reason"), str) else None,
            usage=None if usage is None else dict(usage),
            provider_response=dict(payload),
            provider_id=plan.profile.provider_id,
            plan_digest=plan.plan_digest,
            response_bytes=response_bytes,
            content_blocks=content_blocks,
        )


class OpenAIResponsesProtocol:
    protocol_id = "openai.responses"

    @staticmethod
    def _headers(
        plan: ModelProviderRequestPlan,
        api_key: str,
    ) -> tuple[tuple[str, str], ...]:
        if not api_key:
            return ()
        if plan.profile.provider_id == "azure":
            return (("api-key", api_key),)
        return (("Authorization", f"Bearer {api_key}"),)

    @staticmethod
    def _response_tool(tool: object) -> dict[str, object]:
        if not isinstance(tool, Mapping):
            raise ModelProviderRequestUnsupported("Responses tool must be an object")
        function = tool.get("function")
        if not isinstance(function, Mapping):
            raise ModelProviderRequestUnsupported(
                "canonical tool must contain a function object"
            )
        name = function.get("name")
        parameters = function.get("parameters", {})
        if not isinstance(name, str) or not name:
            raise ModelProviderRequestUnsupported("canonical tool name is required")
        if not isinstance(parameters, Mapping):
            raise ModelProviderRequestUnsupported(
                "canonical tool parameters must be an object"
            )
        row: dict[str, object] = {
            "type": "function",
            "name": name,
            "parameters": dict(parameters),
        }
        description = function.get("description")
        if isinstance(description, str) and description:
            row["description"] = description
        strict = function.get("strict")
        if isinstance(strict, bool):
            row["strict"] = strict
        return row

    @staticmethod
    def _input_items(raw_messages: object) -> list[dict[str, object]]:
        if not isinstance(raw_messages, (tuple, list)):
            raise ModelProviderRequestUnsupported(
                "Responses canonical messages must be an array"
            )
        items: list[dict[str, object]] = []
        for message in raw_messages:
            if not isinstance(message, Mapping):
                raise ModelProviderRequestUnsupported(
                    "canonical message must be an object"
                )
            role = message.get("role")
            if role not in {"system", "developer", "user", "assistant", "tool"}:
                raise ModelProviderRequestUnsupported(
                    f"Responses protocol does not support message role: {role!r}"
                )

            # Replay provider-native state items first. This is what preserves
            # encrypted/signed reasoning across stateless turns.
            blocks = message.get("content_blocks")
            if isinstance(blocks, (tuple, list)):
                for block in blocks:
                    if not isinstance(block, Mapping):
                        continue
                    payload = block.get("provider_payload")
                    if (
                        isinstance(payload, Mapping)
                        and isinstance(payload.get("type"), str)
                        and payload.get("type") in {
                            "reasoning",
                            "function_call",
                            "computer_call",
                            "web_search_call",
                            "file_search_call",
                            "code_interpreter_call",
                        }
                    ):
                        items.append(dict(thaw_json(freeze_json(payload))))

            if role == "tool":
                call_id = message.get("tool_call_id")
                if not isinstance(call_id, str) or not call_id:
                    raise ModelProviderRequestUnsupported(
                        "Responses tool result requires tool_call_id"
                    )
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": _message_content(message.get("content")),
                    }
                )
                continue

            text = _message_content(message.get("content"))
            if text:
                items.append(
                    {
                        "type": "message",
                        "role": role,
                        "content": [
                            {
                                "type": (
                                    "output_text"
                                    if role == "assistant"
                                    else "input_text"
                                ),
                                "text": text,
                            }
                        ],
                    }
                )
            raw_calls = message.get("tool_calls")
            if isinstance(raw_calls, (tuple, list)):
                calls = _canonical_tool_calls(raw_calls)
                for call in calls:
                    function = call["function"]
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": call["id"],
                            "name": function["name"],
                            "arguments": json.dumps(
                                thaw_json(freeze_json(function["arguments"])),
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                        }
                    )
        if not items:
            raise ModelProviderRequestUnsupported(
                "Responses protocol requires at least one canonical input item"
            )
        return items

    @staticmethod
    def _response_format(value: object) -> dict[str, object] | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ModelProviderRequestUnsupported(
                "Responses response_format must be an object"
            )
        kind = value.get("type")
        if kind == "json_object":
            return {"format": {"type": "json_object"}}
        if kind == "json_schema":
            raw = value.get("json_schema")
            if not isinstance(raw, Mapping):
                raise ModelProviderRequestUnsupported(
                    "Responses json_schema response_format is malformed"
                )
            name = raw.get("name", "response")
            schema = raw.get("schema", raw)
            if not isinstance(name, str) or not name:
                raise ModelProviderRequestUnsupported(
                    "Responses json_schema name is invalid"
                )
            if not isinstance(schema, Mapping):
                raise ModelProviderRequestUnsupported(
                    "Responses json_schema schema is invalid"
                )
            fmt: dict[str, object] = {
                "type": "json_schema",
                "name": name,
                "schema": dict(schema),
            }
            strict = raw.get("strict")
            if isinstance(strict, bool):
                fmt["strict"] = strict
            return {"format": fmt}
        if kind in (None, "text"):
            return None
        raise ModelProviderRequestUnsupported(
            f"Responses response_format type is unsupported: {kind!r}"
        )

    def encode(
        self,
        plan: ModelProviderRequestPlan,
        *,
        api_key: str = "",
    ) -> ModelProviderWirePlan:
        if plan.profile.protocol_id != self.protocol_id:
            raise ValueError(
                "OpenAI Responses protocol cannot encode a different provider protocol"
            )
        source = {
            **dict(thaw_json(plan.standard_body)),
            **dict(thaw_json(plan.extra_body)),
        }
        raw_messages = source.pop("messages")
        body: dict[str, object] = {
            "model": plan.backend_model,
            "input": self._input_items(raw_messages),
        }

        max_tokens = source.pop("max_tokens", None)
        max_completion_tokens = source.pop("max_completion_tokens", None)
        if max_tokens is not None and max_completion_tokens is not None:
            raise ModelProviderRequestUnsupported(
                "Responses request specifies both max token aliases"
            )
        if max_completion_tokens is not None:
            body["max_output_tokens"] = max_completion_tokens
        elif max_tokens is not None:
            body["max_output_tokens"] = max_tokens

        response_format = self._response_format(source.pop("response_format", None))
        if response_format is not None:
            body["text"] = response_format

        reasoning_effort = source.pop("reasoning_effort", None)
        if reasoning_effort is not None:
            body["reasoning"] = {"effort": reasoning_effort}

        tools = source.pop("tools", None)
        if tools is not None:
            if not isinstance(tools, (tuple, list)):
                raise ModelProviderRequestUnsupported(
                    "Responses tools must be an array"
                )
            body["tools"] = [self._response_tool(tool) for tool in tools]

        for key in (
            "tool_choice",
            "parallel_tool_calls",
            "temperature",
            "top_p",
            "service_tier",
            "store",
            "metadata",
            "previous_response_id",
            "include",
            "background",
            "prompt_cache_key",
            "prompt_cache_retention",
        ):
            if key in source:
                body[key] = source.pop(key)

        stream = source.pop("stream", None)
        if stream is not None:
            if type(stream) is not bool:
                raise ModelProviderRequestUnsupported(
                    "Responses stream must be boolean"
                )
            if stream:
                body["stream"] = True
        if source:
            raise ModelProviderRequestUnsupported(
                "Responses protocol has unconsumed parameters: "
                + ", ".join(sorted(source))
            )
        raw = canonical_bytes(body)
        return ModelProviderWirePlan(
            plan=plan,
            body=body,
            headers=self._headers(plan, api_key),
            wire_bytes=raw,
        )

    def decode(
        self,
        plan: ModelProviderRequestPlan,
        payload: object,
        *,
        raw_body: bytes | None = None,
    ) -> ModelProviderCompletion:
        if not isinstance(payload, Mapping):
            raise ModelProviderRuntimeError("Responses response must be an object")
        output = payload.get("output")
        if not isinstance(output, (tuple, list)):
            raise ModelProviderRuntimeError("Responses output must be an array")

        texts: list[str] = []
        calls: list[dict[str, object]] = []
        blocks: list[dict[str, object]] = []
        for index, item in enumerate(output):
            if not isinstance(item, Mapping):
                continue
            kind = item.get("type")
            if kind == "message":
                content = item.get("content")
                if not isinstance(content, (tuple, list)):
                    raise ModelProviderRuntimeError(
                        "Responses message content must be an array"
                    )
                for part in content:
                    if not isinstance(part, Mapping):
                        continue
                    part_type = part.get("type")
                    if part_type == "output_text" and isinstance(part.get("text"), str):
                        text = part["text"]
                        texts.append(text)
                        blocks.append(
                            _canonical_content_block(
                                kind="text",
                                provider_id=plan.profile.provider_id,
                                provider_payload=part,
                                text=text,
                            )
                        )
                    elif part_type == "refusal":
                        refusal = part.get("refusal")
                        fields: dict[str, JsonInput] = {}
                        if isinstance(refusal, str):
                            fields["text"] = refusal
                        blocks.append(
                            _canonical_content_block(
                                kind="refusal",
                                provider_id=plan.profile.provider_id,
                                provider_payload=part,
                                **fields,
                            )
                        )
                    else:
                        blocks.append(
                            _canonical_content_block(
                                kind="provider_content",
                                provider_id=plan.profile.provider_id,
                                provider_payload=part,
                            )
                        )
                continue
            if kind == "reasoning":
                summary = item.get("summary")
                reasoning_text = ""
                if isinstance(summary, (tuple, list)):
                    reasoning_text = "".join(
                        part.get("text", "")
                        for part in summary
                        if isinstance(part, Mapping)
                        and isinstance(part.get("text"), str)
                    )
                fields: dict[str, JsonInput] = {}
                if reasoning_text:
                    fields["text"] = reasoning_text
                blocks.append(
                    _canonical_content_block(
                        kind="reasoning",
                        provider_id=plan.profile.provider_id,
                        provider_payload=item,
                        **fields,
                    )
                )
                continue
            if kind == "function_call":
                call_id = item.get("call_id") or item.get("id")
                name = item.get("name")
                arguments = item.get("arguments", {})
                if not isinstance(call_id, str) or not call_id:
                    raise ModelProviderRuntimeError(
                        "Responses function_call call_id is invalid"
                    )
                if not isinstance(name, str) or not name:
                    raise ModelProviderRuntimeError(
                        "Responses function_call name is invalid"
                    )
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError as exc:
                        raise ModelProviderRuntimeError(
                            "Responses function_call arguments are invalid JSON"
                        ) from exc
                if not isinstance(arguments, Mapping):
                    raise ModelProviderRuntimeError(
                        "Responses function_call arguments must be an object"
                    )
                call = {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": dict(arguments),
                    },
                }
                calls.append(call)
                blocks.append(
                    _canonical_content_block(
                        kind="tool_call",
                        provider_id=plan.profile.provider_id,
                        provider_payload=item,
                        tool_call=call,
                    )
                )
                continue
            blocks.append(
                _canonical_content_block(
                    kind="provider_content",
                    provider_id=plan.profile.provider_id,
                    provider_payload=item,
                )
            )

        usage = payload.get("usage")
        if usage is not None and not isinstance(usage, Mapping):
            raise ModelProviderRuntimeError("Responses usage must be an object")
        normalized_usage = None
        if isinstance(usage, Mapping):
            normalized_usage = {
                **dict(usage),
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
            }
        finish_reason: str | None = None
        status = payload.get("status")
        if isinstance(status, str):
            finish_reason = "stop" if status == "completed" else status
        response_bytes = raw_body if raw_body is not None else canonical_bytes(payload)
        return ModelProviderCompletion(
            text="".join(texts),
            tool_calls=tuple(calls),
            finish_reason=finish_reason,
            usage=normalized_usage,
            provider_response=dict(payload),
            provider_id=plan.profile.provider_id,
            plan_digest=plan.plan_digest,
            response_bytes=response_bytes,
            content_blocks=tuple(blocks),
        )


class AnthropicMessagesProtocol:
    protocol_id = "anthropic.messages"

    @staticmethod
    def _tool(tool: object) -> dict[str, object]:
        if not isinstance(tool, Mapping):
            raise ModelProviderRequestUnsupported("Anthropic tool must be an object")
        function = tool.get("function")
        if not isinstance(function, Mapping):
            raise ModelProviderRequestUnsupported(
                "canonical tool must contain a function object"
            )
        name = function.get("name")
        parameters = function.get("parameters", {})
        if not isinstance(name, str) or not name:
            raise ModelProviderRequestUnsupported("canonical tool name is required")
        if not isinstance(parameters, Mapping):
            raise ModelProviderRequestUnsupported("canonical tool parameters must be an object")
        result: dict[str, object] = {
            "name": name,
            "input_schema": dict(parameters),
        }
        description = function.get("description")
        if isinstance(description, str) and description:
            result["description"] = description
        return result

    @staticmethod
    def _tool_choice(value: object) -> object:
        if value is None:
            return None
        if value == "auto":
            return {"type": "auto"}
        if value == "required":
            return {"type": "any"}
        if value == "none":
            return None
        if isinstance(value, Mapping):
            function = value.get("function")
            if isinstance(function, Mapping) and isinstance(function.get("name"), str):
                return {"type": "tool", "name": function["name"]}
        raise ModelProviderRequestUnsupported("Anthropic tool_choice is unsupported")

    def encode(
        self,
        plan: ModelProviderRequestPlan,
        *,
        api_key: str = "",
    ) -> ModelProviderWirePlan:
        if plan.profile.protocol_id != self.protocol_id:
            raise ValueError("Anthropic protocol cannot encode a different provider protocol")
        source = {
            **dict(thaw_json(plan.standard_body)),
            **dict(thaw_json(plan.extra_body)),
        }
        raw_messages = source.pop("messages")
        system_parts: list[str] = []
        messages: list[dict[str, object]] = []
        for message in raw_messages:
            if not isinstance(message, Mapping):
                raise ModelProviderRequestUnsupported("canonical message must be an object")
            role = message.get("role")
            if role == "system":
                text = _message_content(message.get("content"))
                if text:
                    system_parts.append(text)
                continue
            if role not in {"user", "assistant", "tool"}:
                raise ModelProviderRequestUnsupported(
                    f"Anthropic protocol does not support message role: {role!r}"
                )
            if role == "tool":
                call_id = message.get("tool_call_id")
                if not isinstance(call_id, str) or not call_id:
                    raise ModelProviderRequestUnsupported(
                        "canonical tool result requires tool_call_id"
                    )
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": call_id,
                                "content": _message_content(message.get("content")),
                            }
                        ],
                    }
                )
                continue
            canonical_blocks = _message_content_blocks(message)
            if canonical_blocks:
                content: object = _anthropic_blocks_from_canonical(
                    message,
                    provider_id=plan.profile.provider_id,
                )
            else:
                content = _message_content(message.get("content"))
                if role == "assistant" and message.get("tool_calls"):
                    blocks: list[dict[str, object]] = []
                    if content:
                        blocks.append({"type": "text", "text": content})
                    for call in _canonical_tool_calls(message.get("tool_calls")):
                        function = call["function"]
                        blocks.append(
                            {
                                "type": "tool_use",
                                "id": call["id"],
                                "name": function["name"],
                                "input": function["arguments"],
                            }
                        )
                    content = blocks
            messages.append({"role": role, "content": content})
        max_tokens = source.pop("max_tokens", None)
        if max_tokens is None:
            max_tokens = source.pop("max_completion_tokens", None)
        if type(max_tokens) is not int or max_tokens <= 0:
            raise ModelProviderRequestUnsupported(
                "Anthropic Messages requires a positive max_tokens"
            )
        body: dict[str, object] = {
            "model": plan.backend_model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if system_parts:
            body["system"] = "\n\n".join(system_parts)
        for key in ("temperature", "top_p", "top_k", "metadata", "service_tier", "thinking"):
            if key in source:
                body[key] = source.pop(key)
        stop = source.pop("stop", None)
        if stop is not None:
            body["stop_sequences"] = [stop] if isinstance(stop, str) else stop
        tools = source.pop("tools", None)
        if tools is not None:
            body["tools"] = [self._tool(tool) for tool in tools]
        tool_choice = self._tool_choice(source.pop("tool_choice", None))
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        stream = source.pop("stream", None)
        if stream is not None:
            if type(stream) is not bool:
                raise ModelProviderRequestUnsupported(
                    "Anthropic stream must be boolean"
                )
            body["stream"] = stream
        if source:
            raise ModelProviderRequestUnsupported(
                "Anthropic protocol has unconsumed parameters: "
                + ", ".join(sorted(source))
            )
        headers: list[tuple[str, str]] = [("anthropic-version", "2023-06-01")]
        if api_key:
            headers.append(("x-api-key", api_key))
        raw = canonical_bytes(body)
        return ModelProviderWirePlan(
            plan=plan,
            body=body,
            headers=tuple(headers),
            wire_bytes=raw,
        )

    def decode(
        self,
        plan: ModelProviderRequestPlan,
        payload: object,
        *,
        raw_body: bytes | None = None,
    ) -> ModelProviderCompletion:
        if not isinstance(payload, Mapping):
            raise ModelProviderRuntimeError("Anthropic response must be an object")
        blocks = payload.get("content")
        if not isinstance(blocks, (tuple, list)):
            raise ModelProviderRuntimeError("Anthropic response content must be an array")
        texts: list[str] = []
        calls: list[dict[str, object]] = []
        content_blocks: list[dict[str, object]] = []
        for block in blocks:
            if not isinstance(block, Mapping):
                continue
            kind = block.get("type")
            if kind == "text" and isinstance(block.get("text"), str):
                text = block["text"]
                texts.append(text)
                content_blocks.append(_canonical_content_block(
                    kind="text",
                    provider_id=plan.profile.provider_id,
                    provider_payload=block,
                    text=text,
                ))
            elif kind == "thinking":
                thinking = block.get("thinking")
                fields: dict[str, JsonInput] = {}
                if isinstance(thinking, str):
                    fields["text"] = thinking
                signature = block.get("signature")
                if isinstance(signature, str):
                    fields["signature"] = signature
                content_blocks.append(_canonical_content_block(
                    kind="reasoning",
                    provider_id=plan.profile.provider_id,
                    provider_payload=block,
                    **fields,
                ))
            elif kind == "redacted_thinking":
                content_blocks.append(_canonical_content_block(
                    kind="redacted_reasoning",
                    provider_id=plan.profile.provider_id,
                    provider_payload=block,
                ))
            elif kind == "tool_use":
                call_id = block.get("id")
                name = block.get("name")
                arguments = block.get("input", {})
                if not isinstance(call_id, str) or not isinstance(name, str):
                    raise ModelProviderRuntimeError("Anthropic tool_use identity is invalid")
                if not isinstance(arguments, Mapping):
                    raise ModelProviderRuntimeError("Anthropic tool_use input is invalid")
                call = {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": dict(arguments)},
                }
                calls.append(call)
                content_blocks.append(_canonical_content_block(
                    kind="tool_call",
                    provider_id=plan.profile.provider_id,
                    provider_payload=block,
                    tool_call=call,
                ))
            else:
                content_blocks.append(_canonical_content_block(
                    kind="provider_content",
                    provider_id=plan.profile.provider_id,
                    provider_payload=block,
                ))
        usage = payload.get("usage")
        if usage is not None and not isinstance(usage, Mapping):
            raise ModelProviderRuntimeError("Anthropic usage must be an object")
        normalized_usage = None
        if isinstance(usage, Mapping):
            normalized_usage = {
                **dict(usage),
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
            }
        response_bytes = raw_body if raw_body is not None else canonical_bytes(payload)
        return ModelProviderCompletion(
            text="".join(texts),
            tool_calls=tuple(calls),
            finish_reason=payload.get("stop_reason") if isinstance(payload.get("stop_reason"), str) else None,
            usage=normalized_usage,
            provider_response=dict(payload),
            provider_id=plan.profile.provider_id,
            plan_digest=plan.plan_digest,
            response_bytes=response_bytes,
            content_blocks=tuple(content_blocks),
        )


class GoogleGenerateContentProtocol:
    protocol_id = "google.generate-content"

    @staticmethod
    def _tool(tool: object) -> dict[str, object]:
        if not isinstance(tool, Mapping) or not isinstance(tool.get("function"), Mapping):
            raise ModelProviderRequestUnsupported(
                "Gemini canonical tool must contain a function object"
            )
        function = tool["function"]
        name = function.get("name")
        parameters = function.get("parameters", {})
        if not isinstance(name, str) or not name or not isinstance(parameters, Mapping):
            raise ModelProviderRequestUnsupported("Gemini canonical tool is malformed")
        result: dict[str, object] = {
            "name": name,
            "parameters": dict(parameters),
        }
        description = function.get("description")
        if isinstance(description, str) and description:
            result["description"] = description
        return result

    @staticmethod
    def _tool_mode(value: object) -> str | None:
        if value is None:
            return None
        if value == "auto":
            return "AUTO"
        if value == "required":
            return "ANY"
        if value == "none":
            return "NONE"
        if isinstance(value, Mapping):
            return "ANY"
        raise ModelProviderRequestUnsupported("Gemini tool_choice is unsupported")

    def encode(
        self,
        plan: ModelProviderRequestPlan,
        *,
        api_key: str = "",
    ) -> ModelProviderWirePlan:
        if plan.profile.protocol_id != self.protocol_id:
            raise ValueError("Gemini protocol cannot encode a different provider protocol")
        source = {
            **dict(thaw_json(plan.standard_body)),
            **dict(thaw_json(plan.extra_body)),
        }
        raw_messages = source.pop("messages")
        system_parts: list[str] = []
        contents: list[dict[str, object]] = []
        for message in raw_messages:
            if not isinstance(message, Mapping):
                raise ModelProviderRequestUnsupported("canonical message must be an object")
            role = message.get("role")
            text = _message_content(message.get("content"))
            if role == "system":
                if text:
                    system_parts.append(text)
                continue
            if role == "tool":
                name = message.get("name")
                if not isinstance(name, str) or not name:
                    raise ModelProviderRequestUnsupported(
                        "Gemini tool result requires canonical message name"
                    )
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": name,
                                    "response": {"result": text},
                                }
                            }
                        ],
                    }
                )
                continue
            if role not in {"user", "assistant"}:
                raise ModelProviderRequestUnsupported(
                    f"Gemini protocol does not support message role: {role!r}"
                )
            canonical_blocks = _message_content_blocks(message)
            if canonical_blocks:
                parts = _google_parts_from_canonical(
                    message,
                    provider_id=plan.profile.provider_id,
                )
            else:
                parts: list[dict[str, object]] = []
                if text:
                    parts.append({"text": text})
                if role == "assistant" and message.get("tool_calls"):
                    for call in _canonical_tool_calls(message.get("tool_calls")):
                        function = call["function"]
                        parts.append(
                            {
                                "functionCall": {
                                    "name": function["name"],
                                    "args": function["arguments"],
                                }
                            }
                        )
            contents.append(
                {
                    "role": "model" if role == "assistant" else "user",
                    "parts": parts,
                }
            )
        body: dict[str, object] = {"contents": contents}
        if system_parts:
            body["systemInstruction"] = {
                "role": "system",
                "parts": [{"text": "\n\n".join(system_parts)}],
            }
        config: dict[str, object] = {}
        mapping = {
            "max_tokens": "maxOutputTokens",
            "max_completion_tokens": "maxOutputTokens",
            "temperature": "temperature",
            "top_p": "topP",
            "top_k": "topK",
            "seed": "seed",
        }
        for canonical, native in mapping.items():
            if canonical in source:
                if native in config:
                    raise ModelProviderRequestUnsupported(
                        "Gemini request specifies both max token aliases"
                    )
                config[native] = source.pop(canonical)
        stop = source.pop("stop", None)
        if stop is not None:
            config["stopSequences"] = [stop] if isinstance(stop, str) else stop
        response_format = source.pop("response_format", None)
        if response_format is not None:
            if not isinstance(response_format, Mapping):
                raise ModelProviderRequestUnsupported(
                    "Gemini response_format must be an object"
                )
            response_type = response_format.get("type")
            if response_type == "json_object":
                config["responseMimeType"] = "application/json"
            elif response_type == "json_schema":
                config["responseMimeType"] = "application/json"
                schema = response_format.get("json_schema")
                if isinstance(schema, Mapping):
                    schema = schema.get("schema", schema)
                if not isinstance(schema, Mapping):
                    raise ModelProviderRequestUnsupported(
                        "Gemini json_schema response_format is malformed"
                    )
                config["responseJsonSchema"] = dict(schema)
            elif response_type not in (None, "text"):
                raise ModelProviderRequestUnsupported(
                    f"Gemini response_format type is unsupported: {response_type!r}"
                )
        if config:
            body["generationConfig"] = config
        tools = source.pop("tools", None)
        if tools is not None:
            body["tools"] = [
                {"functionDeclarations": [self._tool(tool) for tool in tools]}
            ]
        mode = self._tool_mode(source.pop("tool_choice", None))
        if mode is not None:
            tool_config: dict[str, object] = {
                "functionCallingConfig": {"mode": mode}
            }
            body["toolConfig"] = tool_config
        stream = source.pop("stream", None)
        if stream is not None and type(stream) is not bool:
            raise ModelProviderRequestUnsupported(
                "Gemini stream must be boolean"
            )
        if source:
            raise ModelProviderRequestUnsupported(
                "Gemini protocol has unconsumed parameters: "
                + ", ".join(sorted(source))
            )
        headers = (("x-goog-api-key", api_key),) if api_key else ()
        raw = canonical_bytes(body)
        return ModelProviderWirePlan(
            plan=plan,
            body=body,
            headers=headers,
            wire_bytes=raw,
        )

    def decode(
        self,
        plan: ModelProviderRequestPlan,
        payload: object,
        *,
        raw_body: bytes | None = None,
    ) -> ModelProviderCompletion:
        if not isinstance(payload, Mapping):
            raise ModelProviderRuntimeError("Gemini response must be an object")
        candidates = payload.get("candidates")
        if not isinstance(candidates, (tuple, list)) or len(candidates) != 1:
            raise ModelProviderRuntimeError(
                "Gemini response must contain exactly one candidate"
            )
        candidate = candidates[0]
        if not isinstance(candidate, Mapping):
            raise ModelProviderRuntimeError("Gemini candidate must be an object")
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, Mapping) else None
        if not isinstance(parts, (tuple, list)):
            raise ModelProviderRuntimeError("Gemini candidate content is malformed")
        texts: list[str] = []
        calls: list[dict[str, object]] = []
        content_blocks: list[dict[str, object]] = []
        for index, part in enumerate(parts):
            if not isinstance(part, Mapping):
                continue
            text = part.get("text")
            function = part.get("functionCall")
            thought = part.get("thought") is True
            if isinstance(function, Mapping):
                name = function.get("name")
                args = function.get("args", {})
                if not isinstance(name, str) or not name or not isinstance(args, Mapping):
                    raise ModelProviderRuntimeError("Gemini functionCall is malformed")
                call = {
                    "id": f"gemini-call-{index}",
                    "type": "function",
                    "function": {"name": name, "arguments": dict(args)},
                }
                calls.append(call)
                content_blocks.append(_canonical_content_block(
                    kind="tool_call",
                    provider_id=plan.profile.provider_id,
                    provider_payload=part,
                    tool_call=call,
                ))
                continue
            if isinstance(text, str):
                if thought:
                    content_blocks.append(_canonical_content_block(
                        kind="reasoning",
                        provider_id=plan.profile.provider_id,
                        provider_payload=part,
                        text=text,
                    ))
                else:
                    texts.append(text)
                    content_blocks.append(_canonical_content_block(
                        kind="text",
                        provider_id=plan.profile.provider_id,
                        provider_payload=part,
                        text=text,
                    ))
                continue
            if "inlineData" in part or "fileData" in part:
                content_blocks.append(_canonical_content_block(
                    kind="media",
                    provider_id=plan.profile.provider_id,
                    provider_payload=part,
                ))
            else:
                content_blocks.append(_canonical_content_block(
                    kind="provider_content",
                    provider_id=plan.profile.provider_id,
                    provider_payload=part,
                ))
        usage = payload.get("usageMetadata")
        normalized_usage = None
        if isinstance(usage, Mapping):
            normalized_usage = {
                **dict(usage),
                "prompt_tokens": usage.get("promptTokenCount"),
                "completion_tokens": usage.get("candidatesTokenCount"),
                "total_tokens": usage.get("totalTokenCount"),
            }
        response_bytes = raw_body if raw_body is not None else canonical_bytes(payload)
        return ModelProviderCompletion(
            text="".join(texts),
            tool_calls=tuple(calls),
            finish_reason=candidate.get("finishReason") if isinstance(candidate.get("finishReason"), str) else None,
            usage=normalized_usage,
            provider_response=dict(payload),
            provider_id=plan.profile.provider_id,
            plan_digest=plan.plan_digest,
            response_bytes=response_bytes,
            content_blocks=tuple(content_blocks),
        )


class NativeModelProviderProtocolRegistry:
    def __init__(self) -> None:
        protocols = (
            OpenAIChatProtocol(),
            OpenAIResponsesProtocol(),
            AnthropicMessagesProtocol(),
            GoogleGenerateContentProtocol(),
        )
        self._protocols = {protocol.protocol_id: protocol for protocol in protocols}
        self.registry_digest = canonical_digest(
            {
                "schema": "noetrium.native-model-provider-protocol-registry.v1",
                "protocols": tuple(sorted(self._protocols)),
            }
        )

    def resolve(self, protocol_id: str):
        protocol = self._protocols.get(protocol_id)
        if protocol is None:
            raise ModelProviderRequestUnsupported(
                f"native provider protocol is not implemented: {protocol_id}"
            )
        return protocol

    def encode(
        self,
        plan: ModelProviderRequestPlan,
        *,
        api_key: str = "",
    ) -> ModelProviderWirePlan:
        return self.resolve(plan.profile.protocol_id).encode(plan, api_key=api_key)

    def decode(
        self,
        plan: ModelProviderRequestPlan,
        payload: object,
        *,
        raw_body: bytes | None = None,
    ) -> ModelProviderCompletion:
        return self.resolve(plan.profile.protocol_id).decode(
            plan,
            payload,
            raw_body=raw_body,
        )


__all__ = [
    "AnthropicMessagesProtocol",
    "GoogleGenerateContentProtocol",
    "ModelProviderWirePlan",
    "NativeModelProviderCatalog",
    "NativeModelProviderProfileResolver",
    "NativeModelProviderProtocolRegistry",
    "NativeModelProviderSpec",
    "OpenAIChatProtocol",
    "OpenAIResponsesProtocol",
    "provider_error_detail",
    "provider_profile_for_protocol",
]
