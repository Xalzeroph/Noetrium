from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from noetrium_platform.capabilities.model.request.api import ModelRequestRecorderPort
from noetrium_platform.capabilities.model.serving.endpoint.api import (
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
    canonical_digest,
    freeze_json,
)

from ..api import MethodAgentRequest, MethodAgentResult, MethodEvent


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

    def build(self, request: MethodAgentRequest) -> JsonObject:
        prompt = request.view.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("method model request view requires non-empty prompt")
        return {
            "model": self.served_model_name,
            "messages": ({"role": "user", "content": prompt},),
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
        request_factory: PromptViewChatRequestFactory,
    ) -> None:
        if not isinstance(binding, MethodModelEndpointBinding):
            raise TypeError("binding must be MethodModelEndpointBinding")
        if not hasattr(endpoint, "route") or not callable(getattr(endpoint, "complete", None)):
            raise TypeError("endpoint must expose route and complete")
        if not isinstance(recorder, ModelRequestRecorderPort):
            raise TypeError("recorder must satisfy ModelRequestRecorderPort")
        if not isinstance(request_factory, PromptViewChatRequestFactory):
            raise TypeError("request_factory must be PromptViewChatRequestFactory")
        if binding.request_factory_digest != request_factory.digest:
            raise ValueError("method model request factory identity drift")
        self.binding = binding
        self.endpoint = endpoint
        self.recorder = recorder
        self.request_factory = request_factory

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
        prompt = request.view.get("prompt")
        envelope = self.recorder.record(
            request_id=request_id,
            context=request.context,
            role=self.binding.role,
            model=self.binding.model,
            prompt_generation_id=self.binding.prompt_generation_id,
            prompt_id=self.binding.prompt_id,
            prompt_digest=self.binding.prompt_digest,
            request_body=body,
            compiled_prompt_text=prompt if isinstance(prompt, str) else None,
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


__all__ = [
    "EndpointBackedMethodAgentLoop",
    "MethodModelEndpointBinding",
    "PromptViewChatRequestFactory",
]
