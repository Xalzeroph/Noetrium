from __future__ import annotations

from collections.abc import Mapping
import json
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.model.request.api import ModelRequestRecorderPort
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointDispatchPoolPort,
    ModelEndpointPort,
    ModelEndpointRequest,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ImmutableModelIdentity,
    JsonInput,
    JsonObject,
    canonical_bytes,
    canonical_digest,
    freeze_json,
    require_sha256,
)

from ..api import MethodAgentLoopPort, MethodAgentRequest, MethodAgentResult, MethodEvent


@runtime_checkable
class MethodAgentRequestFactoryPort(Protocol):
    @property
    def digest(self) -> str: ...

    def build(self, request: MethodAgentRequest) -> JsonObject: ...

    def compiled_prompt_text(self, request: MethodAgentRequest) -> str: ...


@dataclass(frozen=True, slots=True)
class PromptViewChatRequestFactory:
    """Generic chat request factory for method views exposing a compiled prompt."""

    served_model_name: str
    generation_options: JsonObject

    def __post_init__(self) -> None:
        if not isinstance(self.served_model_name, str) or not self.served_model_name.strip():
            raise ValueError("served model name is required")
        if not isinstance(self.generation_options, Mapping):
            raise TypeError("generation_options must be a mapping")
        object.__setattr__(self, "generation_options", freeze_json(self.generation_options))
        forbidden = {"model", "messages"} & set(self.generation_options)
        if forbidden:
            raise ValueError(
                "generation_options must not override model/messages: "
                + ", ".join(sorted(forbidden))
            )

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "factory": "prompt-view-chat.v1",
                "served_model_name": self.served_model_name,
                "generation_options": self.generation_options,
            }
        )

    def compiled_prompt_text(self, request: MethodAgentRequest) -> str:
        prompt = request.view.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("method model request view requires non-empty prompt")
        return prompt

    def build(self, request: MethodAgentRequest) -> JsonObject:
        return {
            "model": self.served_model_name,
            "messages": ({"role": "user", "content": self.compiled_prompt_text(request)},),
            **dict(self.generation_options),
        }


@dataclass(frozen=True, slots=True)
class StructuredViewChatRequestFactory:
    """Deterministically compile a generic Method agent view into one chat prompt.

    This is intentionally paper-agnostic. Paper-specific prompt semantics should
    still supply an explicit PromptViewChatRequestFactory instead. The structured
    factory is for generic phase/workflow methods whose MethodProgram already
    exposes the exact model-visible instruction/input/state view.
    """

    served_model_name: str
    generation_options: JsonObject
    system_instruction: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.served_model_name, str) or not self.served_model_name.strip():
            raise ValueError("served model name is required")
        if not isinstance(self.generation_options, Mapping):
            raise TypeError("generation_options must be a mapping")
        object.__setattr__(self, "generation_options", freeze_json(self.generation_options))
        forbidden = {"model", "messages"} & set(self.generation_options)
        if forbidden:
            raise ValueError(
                "generation_options must not override model/messages: "
                + ", ".join(sorted(forbidden))
            )
        if self.system_instruction is not None and (
            not isinstance(self.system_instruction, str)
            or not self.system_instruction.strip()
        ):
            raise ValueError("system_instruction must be non-empty or None")

    @property
    def digest(self) -> str:
        return canonical_digest({
            "factory": "structured-method-view-chat.v1",
            "served_model_name": self.served_model_name,
            "generation_options": self.generation_options,
            "system_instruction": self.system_instruction,
        })

    def compiled_prompt_text(self, request: MethodAgentRequest) -> str:
        view = json.loads(canonical_bytes(request.view))
        instruction = view.pop("instruction", None) if isinstance(view, dict) else None
        sections: list[str] = []
        if self.system_instruction is not None:
            sections.append(self.system_instruction.strip())
        if isinstance(instruction, str) and instruction.strip():
            sections.append(instruction.strip())
        sections.append(
            "Method context (canonical JSON):\n"
            + json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        return "\n\n".join(sections)

    def build(self, request: MethodAgentRequest) -> JsonObject:
        return {
            "model": self.served_model_name,
            "messages": ({"role": "user", "content": self.compiled_prompt_text(request)},),
            **dict(self.generation_options),
        }


@dataclass(frozen=True, slots=True)
class MethodModelEndpointBinding:
    """Exact model/prompt/deployment identity for one method-agent target."""

    agent_id: str
    role: str
    model: ImmutableModelIdentity
    prompt_generation_id: str
    prompt_id: str
    prompt_digest: str
    request_factory_digest: str

    def __post_init__(self) -> None:
        for name in (
            "agent_id",
            "role",
            "prompt_generation_id",
            "prompt_id",
            "prompt_digest",
            "request_factory_digest",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"method model binding {name} is required")
        if not isinstance(self.model, ImmutableModelIdentity):
            raise TypeError("method model binding model must be ImmutableModelIdentity")
        if len(self.prompt_digest) != 64 or len(self.request_factory_digest) != 64:
            raise ValueError("method model binding digests must be SHA-256 hex")

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "agent_id": self.agent_id,
                "role": self.role,
                "model": self.model,
                "prompt_generation_id": self.prompt_generation_id,
                "prompt_id": self.prompt_id,
                "prompt_digest": self.prompt_digest,
                "request_factory_digest": self.request_factory_digest,
            }
        )


class EndpointBackedMethodAgentLoop:
    """Paper-agnostic MethodAgentLoop backed by a typed model endpoint.

    This adapter records the exact model-visible request before transport and
    returns one standard EffectReceipt plus one model.invocation MethodEvent.
    Qualification policy remains outside this class: callers may bind either a
    qualified endpoint or an explicitly labelled external/substitute endpoint.
    """

    def __init__(
        self,
        *,
        binding: MethodModelEndpointBinding,
        endpoint: ModelEndpointPort,
        recorder: ModelRequestRecorderPort,
        request_factory: MethodAgentRequestFactoryPort,
    ) -> None:
        if not isinstance(binding, MethodModelEndpointBinding):
            raise TypeError("binding must be MethodModelEndpointBinding")
        if not hasattr(endpoint, "route") or not callable(getattr(endpoint, "complete", None)):
            raise TypeError("endpoint must expose route and complete")
        if not isinstance(recorder, ModelRequestRecorderPort):
            raise TypeError("recorder must satisfy ModelRequestRecorderPort")
        if not isinstance(request_factory, MethodAgentRequestFactoryPort):
            raise TypeError("request_factory must satisfy MethodAgentRequestFactoryPort")
        if binding.request_factory_digest != request_factory.digest:
            raise ValueError("method model request factory identity drift")
        self.binding = binding
        self.endpoint = endpoint
        self.recorder = recorder
        self.request_factory = request_factory

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "binding_digest": self.binding.digest,
            "endpoint_route": self.endpoint.route,
            "request_factory_digest": self.request_factory.digest,
        })

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if not isinstance(request, MethodAgentRequest):
            raise TypeError("method model agent requires MethodAgentRequest")
        if request.agent_id != self.binding.agent_id:
            raise ValueError("method model agent target identity drift")
        route = self.endpoint.route
        operation_id = request.context.operation_id
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("method model invocation requires operation_id")
        body = self.request_factory.build(request)
        request_id = (
            "method-model:"
            + canonical_digest(
                {
                    "operation_id": operation_id,
                    "binding_digest": self.binding.digest,
                    "body": body,
                }
            )
        )
        compiled_prompt_text = self.request_factory.compiled_prompt_text(request)
        envelope = self.recorder.record(
            request_id=request_id,
            context=request.context,
            role=self.binding.role,
            model=self.binding.model,
            prompt_generation_id=self.binding.prompt_generation_id,
            prompt_id=self.binding.prompt_id,
            prompt_digest=self.binding.prompt_digest,
            request_body=body,
            compiled_prompt_text=compiled_prompt_text,
        )
        self.recorder.verify_visible_request(envelope, body)
        endpoint_request = ModelEndpointRequest(
            request=envelope,
            deployment_id=route.deployment_id,
            deployment_generation=route.deployment_generation,
            body=body,
        )
        response = self.endpoint.complete(endpoint_request)
        receipt = EffectReceipt(
            effect_id=f"model-response:{response.response_digest}",
            request_digest=endpoint_request.digest(),
            effect_class=EffectClass.RECONCILABLE,
            certainty=EffectCertainty.EFFECT_CONFIRMED,
            provider_instance_id=route.deployment_id,
            verification_required=False,
            provider_receipt=response.response_digest,
        )
        event = MethodEvent(
            "model.invocation",
            {
                "request_id": envelope.request_id,
                "request_digest": endpoint_request.digest(),
                "response_digest": response.response_digest,
                "deployment_id": response.deployment_id,
                "model_id": self.binding.model.model_id,
                "model_revision": self.binding.model.revision,
                "engine": self.binding.model.engine,
                "engine_version": self.binding.model.engine_version,
                "finish_reason": response.finish_reason,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "usage": response.usage,
            },
        )
        return MethodAgentResult(
            value=response.text,
            events=(event,),
            effect_receipts=(receipt,),
        )


class DispatchPoolBackedMethodAgentLoop:
    """Paper-agnostic MethodAgentLoop backed by a shared replica dispatch pool.

    The logical request is recorded exactly once before dispatch. The pool then
    selects one frozen physical deployment. No failed request is replayed onto a
    second replica, preserving the same fail-closed external-effect semantics as
    the endpoint pool itself.
    """

    def __init__(
        self,
        *,
        binding: MethodModelEndpointBinding,
        pool: ModelEndpointDispatchPoolPort,
        recorder: ModelRequestRecorderPort,
        request_factory: MethodAgentRequestFactoryPort,
    ) -> None:
        if not isinstance(binding, MethodModelEndpointBinding):
            raise TypeError("binding must be MethodModelEndpointBinding")
        if not isinstance(pool, ModelEndpointDispatchPoolPort):
            raise TypeError("pool must satisfy ModelEndpointDispatchPoolPort")
        if not isinstance(recorder, ModelRequestRecorderPort):
            raise TypeError("recorder must satisfy ModelRequestRecorderPort")
        if not isinstance(request_factory, MethodAgentRequestFactoryPort):
            raise TypeError("request_factory must satisfy MethodAgentRequestFactoryPort")
        if binding.request_factory_digest != request_factory.digest:
            raise ValueError("method model request factory identity drift")
        snapshot = pool.snapshot()
        require_sha256(snapshot.replica_set_digest, "method model replica_set_digest")
        self.binding = binding
        self.pool = pool
        self.recorder = recorder
        self.request_factory = request_factory
        self._replica_set_digest = snapshot.replica_set_digest
        self._selection_policy_digest = snapshot.selection_policy_digest
        require_sha256(
            self._selection_policy_digest,
            "method model selection_policy_digest",
        )

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "binding_digest": self.binding.digest,
            "replica_set_digest": self._replica_set_digest,
            "selection_policy_digest": self._selection_policy_digest,
            "request_factory_digest": self.request_factory.digest,
        })

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if not isinstance(request, MethodAgentRequest):
            raise TypeError("method model agent requires MethodAgentRequest")
        if request.agent_id != self.binding.agent_id:
            raise ValueError("method model agent target identity drift")
        operation_id = request.context.operation_id
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("method model invocation requires operation_id")
        body = self.request_factory.build(request)
        request_id = (
            "method-model-pool:"
            + canonical_digest({
                "operation_id": operation_id,
                "binding_digest": self.binding.digest,
                "replica_set_digest": self._replica_set_digest,
                "body": body,
            })
        )
        compiled_prompt_text = self.request_factory.compiled_prompt_text(request)
        envelope = self.recorder.record(
            request_id=request_id,
            context=request.context,
            role=self.binding.role,
            model=self.binding.model,
            prompt_generation_id=self.binding.prompt_generation_id,
            prompt_id=self.binding.prompt_id,
            prompt_digest=self.binding.prompt_digest,
            request_body=body,
            compiled_prompt_text=compiled_prompt_text,
        )
        self.recorder.verify_visible_request(envelope, body)
        dispatch = self.pool.complete(envelope, body)
        if dispatch.replica_set_digest != self._replica_set_digest:
            raise RuntimeError("method model replica-set identity drift during dispatch")
        if dispatch.selection_policy_digest != self._selection_policy_digest:
            raise RuntimeError("method model selection-policy identity drift during dispatch")
        response = dispatch.response
        receipt = EffectReceipt(
            effect_id=f"model-response:{response.response_digest}",
            request_digest=dispatch.request.digest(),
            effect_class=EffectClass.RECONCILABLE,
            certainty=EffectCertainty.EFFECT_CONFIRMED,
            provider_instance_id=response.deployment_id,
            verification_required=False,
            provider_receipt=response.response_digest,
        )
        event = MethodEvent(
            "model.invocation",
            {
                "request_id": envelope.request_id,
                "request_digest": dispatch.request.digest(),
                "response_digest": response.response_digest,
                "deployment_id": response.deployment_id,
                "deployment_generation": dispatch.request.deployment_generation,
                "replica_set_digest": dispatch.replica_set_digest,
                "selection_policy_digest": dispatch.selection_policy_digest,
                "selection_sequence": dispatch.selection_sequence,
                "model_id": self.binding.model.model_id,
                "model_revision": self.binding.model.revision,
                "engine": self.binding.model.engine,
                "engine_version": self.binding.model.engine_version,
                "finish_reason": response.finish_reason,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "usage": response.usage,
            },
        )
        return MethodAgentResult(
            value=response.text,
            events=(event,),
            effect_receipts=(receipt,),
        )


class MethodAgentLoopRouter:
    """Fail-closed router from Method agent identities to bound agent loops."""

    def __init__(self, bindings: Mapping[str, MethodAgentLoopPort]) -> None:
        if not isinstance(bindings, Mapping) or not bindings:
            raise ValueError("method agent router requires at least one binding")
        rows: dict[str, MethodAgentLoopPort] = {}
        identities: list[tuple[str, str]] = []
        for agent_id, loop in bindings.items():
            if not isinstance(agent_id, str) or not agent_id.strip():
                raise ValueError("method agent router ids must be non-empty text")
            if not isinstance(loop, MethodAgentLoopPort):
                raise TypeError("method agent router values must satisfy MethodAgentLoopPort")
            digest = getattr(loop, "identity_digest", None)
            require_sha256(digest, f"method agent router binding {agent_id} identity_digest")
            rows[agent_id] = loop
            identities.append((agent_id, digest))
        self._bindings = rows
        self._identity_digest = canonical_digest({
            "router": "method-agent-loop-router.v1",
            "bindings": tuple(sorted(identities)),
        })

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    @property
    def agent_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._bindings))

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if not isinstance(request, MethodAgentRequest):
            raise TypeError("method agent router requires MethodAgentRequest")
        try:
            loop = self._bindings[request.agent_id]
        except KeyError as exc:
            raise KeyError(
                f"no method agent binding for {request.agent_id!r}; "
                f"available={self.agent_ids!r}"
            ) from exc
        result = loop.run(request)
        if not isinstance(result, MethodAgentResult):
            raise TypeError("method agent binding must return MethodAgentResult")
        return result


__all__ = [
    "DispatchPoolBackedMethodAgentLoop",
    "EndpointBackedMethodAgentLoop",
    "MethodAgentLoopRouter",
    "MethodAgentRequestFactoryPort",
    "MethodModelEndpointBinding",
    "PromptViewChatRequestFactory",
    "StructuredViewChatRequestFactory",
]
