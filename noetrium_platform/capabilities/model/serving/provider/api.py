from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonInput, JsonObject, JsonValue, canonical_bytes, canonical_digest,
    freeze_json, thaw_json,
)

CANONICAL_MODEL_SEED_MIN = 0
CANONICAL_MODEL_SEED_MAX = (1 << 63) - 1
_RUNTIME_OWNED = frozenset({"fallbacks", "retry_policy", "max_retries", "num_retries", "caching"})


class ModelProviderRequestUnsupported(ValueError):
    pass


class ModelProviderRuntimeError(RuntimeError):
    def __init__(
        self, message: str, *, status_code: int | None = None,
        request_bytes: bytes = b"", response_bytes: bytes = b"",
    ) -> None:
        super().__init__(message)
        if status_code is not None and (
            type(status_code) is not int or not 100 <= status_code <= 599
        ):
            raise ValueError("provider status_code must be an HTTP status")
        if type(request_bytes) is not bytes or type(response_bytes) is not bytes:
            raise TypeError("provider evidence must be exact bytes")
        self.status_code = status_code
        self.request_bytes = request_bytes
        self.response_bytes = response_bytes


@dataclass(frozen=True, slots=True)
class ModelProviderRuntimeProfile:
    provider_id: str
    logical_model_name: str
    provider_model_name: str
    supported_parameters: tuple[str, ...]
    passthrough_parameters: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    protocol_id: str = "openai.chat-completions"
    auth_kind: str = "bearer-optional"
    profile_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "provider_id", "logical_model_name", "provider_model_name",
            "protocol_id", "auth_kind",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"model provider {name} is required")
        for name in ("supported_parameters", "passthrough_parameters", "features"):
            values = getattr(self, name)
            if type(values) is not tuple or any(
                type(item) is not str or not item.strip() for item in values
            ):
                raise TypeError(f"model provider {name} must be a text tuple")
            object.__setattr__(self, name, tuple(sorted(set(values))))
        if set(self.supported_parameters) & set(self.passthrough_parameters):
            raise ValueError("provider standard/passthrough parameters overlap")
        object.__setattr__(self, "profile_digest", canonical_digest({
            "schema": "noetrium.model-provider-runtime-profile.v1",
            "provider_id": self.provider_id,
            "logical_model_name": self.logical_model_name,
            "provider_model_name": self.provider_model_name,
            "supported_parameters": self.supported_parameters,
            "passthrough_parameters": self.passthrough_parameters,
            "features": self.features,
            "protocol_id": self.protocol_id,
            "auth_kind": self.auth_kind,
            "seed_domain": (CANONICAL_MODEL_SEED_MIN, CANONICAL_MODEL_SEED_MAX),
        }))


@dataclass(frozen=True, slots=True)
class ModelProviderRequestPlan:
    profile: ModelProviderRuntimeProfile
    logical_body: JsonObject
    standard_body: JsonObject
    extra_body: JsonObject
    backend_model: str
    request_bytes: bytes
    plan_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.profile, ModelProviderRuntimeProfile):
            raise TypeError("provider plan requires runtime profile")
        for name in ("logical_body", "standard_body", "extra_body"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise TypeError(f"{name} must be a mapping")
            object.__setattr__(self, name, freeze_json(value))
        if type(self.backend_model) is not str or not self.backend_model.strip():
            raise ValueError("provider backend_model is required")
        if type(self.request_bytes) is not bytes:
            raise TypeError("provider request bytes must be exact bytes")
        object.__setattr__(self, "plan_digest", canonical_digest({
            "schema": "noetrium.model-provider-request-plan.v1",
            "profile_digest": self.profile.profile_digest,
            "logical_body": self.logical_body,
            "standard_body": self.standard_body,
            "extra_body": self.extra_body,
            "backend_model": self.backend_model,
            "request_sha256": sha256(self.request_bytes).hexdigest(),
        }))


@dataclass(frozen=True, slots=True)
class ModelProviderCompletion:
    text: str
    tool_calls: JsonValue
    finish_reason: str | None
    usage: JsonValue | None
    provider_response: JsonObject
    provider_id: str
    plan_digest: str
    response_bytes: bytes
    content_blocks: JsonValue = ()
    response_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.text) is not str:
            raise TypeError("provider completion text must be text")
        object.__setattr__(self, "tool_calls", freeze_json(self.tool_calls))
        object.__setattr__(self, "content_blocks", freeze_json(self.content_blocks))
        if not isinstance(self.tool_calls, tuple):
            raise TypeError("provider tool_calls must be a tuple")
        if not isinstance(self.content_blocks, tuple):
            raise TypeError("provider content_blocks must be a tuple")
        for block in self.content_blocks:
            if not isinstance(block, Mapping):
                raise TypeError("provider content block must be an object")
            kind = block.get("kind")
            if type(kind) is not str or not kind.strip():
                raise ValueError("provider content block kind is required")
        if not self.text.strip() and not self.tool_calls and not self.content_blocks:
            raise ValueError("provider completion requires canonical content")
        if self.finish_reason is not None and type(self.finish_reason) is not str:
            raise TypeError("finish_reason must be text or None")
        if self.usage is not None:
            object.__setattr__(self, "usage", freeze_json(self.usage))
        object.__setattr__(self, "provider_response", freeze_json(self.provider_response))
        if type(self.response_bytes) is not bytes:
            raise TypeError("provider response bytes must be exact bytes")
        object.__setattr__(self, "response_digest", canonical_digest({
            "schema": "noetrium.model-provider-completion.v1",
            "provider_id": self.provider_id,
            "plan_digest": self.plan_digest,
            "text": self.text,
            "tool_calls": self.tool_calls,
            "content_blocks": self.content_blocks,
            "finish_reason": self.finish_reason,
            "usage": self.usage,
            "response_sha256": sha256(self.response_bytes).hexdigest(),
        }))


class ModelProviderRequestPlanner:
    def plan(
        self, profile: ModelProviderRuntimeProfile, body: Mapping[str, JsonInput],
    ) -> ModelProviderRequestPlan:
        return self._plan(profile, body, allow_stream=False)

    def plan_stream(
        self, profile: ModelProviderRuntimeProfile, body: Mapping[str, JsonInput],
    ) -> ModelProviderRequestPlan:
        return self._plan(profile, body, allow_stream=True)

    def _plan(
        self,
        profile: ModelProviderRuntimeProfile,
        body: Mapping[str, JsonInput],
        *,
        allow_stream: bool,
    ) -> ModelProviderRequestPlan:
        if type(allow_stream) is not bool:
            raise TypeError("provider allow_stream must be bool")
        if not isinstance(profile, ModelProviderRuntimeProfile):
            raise TypeError("provider planning requires runtime profile")
        logical = freeze_json(body)
        if logical.get("model") != profile.logical_model_name:
            raise ModelProviderRequestUnsupported("logical model does not match provider profile")
        messages = logical.get("messages")
        if not isinstance(messages, tuple) or not messages:
            raise ModelProviderRequestUnsupported("generation requires non-empty messages")
        forbidden = _RUNTIME_OWNED & set(logical)
        if forbidden:
            raise ModelProviderRequestUnsupported(
                "retry/fallback/cache policy is runtime-owned: "
                + ", ".join(sorted(forbidden))
            )
        stream = logical.get("stream")
        if stream not in (None, False, True):
            raise ModelProviderRequestUnsupported("stream must be boolean")
        if stream is True and not allow_stream:
            raise ModelProviderRequestUnsupported(
                "non-streaming engine cannot accept stream=true"
            )
        seed = logical.get("seed")
        if seed is not None and (
            type(seed) is not int
            or not CANONICAL_MODEL_SEED_MIN <= seed <= CANONICAL_MODEL_SEED_MAX
        ):
            raise ModelProviderRequestUnsupported(
                "model sampling seed is outside canonical signed-int64 domain"
            )
        supported = set(profile.supported_parameters)
        passthrough = set(profile.passthrough_parameters)
        standard: dict[str, JsonInput] = {"messages": thaw_json(messages)}
        extra: dict[str, JsonInput] = {}
        unsupported: list[str] = []
        for key, value in logical.items():
            if key in {"model", "messages"}:
                continue
            if key in passthrough:
                extra[key] = thaw_json(value)
            elif key in supported:
                standard[key] = thaw_json(value)
            else:
                unsupported.append(key)
        if unsupported:
            raise ModelProviderRequestUnsupported(
                "provider does not support requested parameters: "
                + ", ".join(sorted(unsupported))
            )
        backend_model = profile.provider_model_name
        wire = {"model": backend_model, **standard, **extra}
        return ModelProviderRequestPlan(
            profile, logical, standard, extra, backend_model, canonical_bytes(wire)
        )


@runtime_checkable
class ModelProviderProfileResolverPort(Protocol):
    def resolve(
        self, *, logical_model_name: str, provider_model_name: str, model_engine: str,
        provider_id: str | None = None,
    ) -> ModelProviderRuntimeProfile: ...


@runtime_checkable
class ModelProviderEnginePort(Protocol):
    def complete(
        self, plan: ModelProviderRequestPlan, *, api_base: str | None,
        api_key: str, timeout_s: float,
    ) -> ModelProviderCompletion: ...


__all__ = [
    "CANONICAL_MODEL_SEED_MAX", "CANONICAL_MODEL_SEED_MIN",
    "ModelProviderCompletion", "ModelProviderEnginePort",
    "ModelProviderProfileResolverPort", "ModelProviderRequestPlan",
    "ModelProviderRequestPlanner", "ModelProviderRequestUnsupported",
    "ModelProviderRuntimeError", "ModelProviderRuntimeProfile",
]
