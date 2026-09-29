from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256

from noetrium_platform.capabilities.model.api import (
    ModelRequestTokenBudget,
    ModelRequestTokenizationIdentity,
    ModelRequestTokenizationPort,
    ModelRequestTokenizationProviderPort,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointError,
    ModelJsonHttpClientPort,
    QualifiedModelEndpointBinding,
)
from noetrium_platform.foundation.kernel.kernel import (
    ImmutableModelIdentity,
    JsonInput,
    canonical_digest,
    strict_finite_json_bytes,
)
from noetrium_platform.foundation.kernel.concurrency.api import SingleFlightCache


class ExactModelTokenizationCache:
    """Bounded exact cache using the platform's sole single-flight primitive."""

    def __init__(self, max_entries: int) -> None:
        self._rows: SingleFlightCache[tuple[int, int]] = SingleFlightCache(
            max_entries=max_entries
        )

    def get_or_create(
        self,
        key: str,
        builder,
    ) -> tuple[int, int]:
        return self._rows.get_or_create(key, builder)

    def __len__(self) -> int:
        return len(self._rows)


@dataclass(frozen=True, slots=True)
class OpenAICompatibleQualifiedTokenization:
    binding: QualifiedModelEndpointBinding
    identity: ModelRequestTokenizationIdentity
    transport: ModelJsonHttpClientPort
    cache: ExactModelTokenizationCache = field(
        default_factory=lambda: ExactModelTokenizationCache(4096),
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.binding, QualifiedModelEndpointBinding):
            raise TypeError("qualified tokenization requires QualifiedModelEndpointBinding")
        if not isinstance(self.identity, ModelRequestTokenizationIdentity):
            raise TypeError("qualified tokenization identity must be typed")
        if self.identity.model != self.binding.model:
            raise ValueError("qualified tokenization model identity drift")
        if self.identity.model_stack_digest != self.binding.model_stack_digest:
            raise ValueError("qualified tokenization stack identity drift")
        if self.identity.tokenizer_sha256 != self.binding.tokenizer_sha256:
            raise ValueError("qualified tokenization tokenizer identity drift")
        if self.identity.chat_template_sha256 != self.binding.chat_template_sha256:
            raise ValueError("qualified tokenization chat-template identity drift")
        if not isinstance(self.transport, ModelJsonHttpClientPort):
            raise TypeError("qualified tokenization requires ModelJsonHttpClientPort")
        if not isinstance(self.cache, ExactModelTokenizationCache):
            raise TypeError("qualified tokenization requires exact cache authority")

    def _payload(self, body: Mapping[str, JsonInput]) -> dict[str, object]:
        messages = body.get("messages")
        if messages is not None:
            payload: dict[str, object] = {
                "model": self.binding.model.logical_name,
                "messages": messages,
                "add_generation_prompt": True,
            }
            for key in ("chat_template_kwargs", "tools"):
                value = body.get(key)
                if value is not None:
                    payload[key] = value
            return payload
        prompt = body.get("prompt")
        if not isinstance(prompt, str):
            raise ValueError(
                "model request tokenization requires chat messages or text prompt"
            )
        return {
            "model": self.binding.model.logical_name,
            "prompt": prompt,
            "add_special_tokens": True,
        }

    @staticmethod
    def _requested_output_tokens(
        body: Mapping[str, JsonInput],
        *,
        input_tokens: int,
        context_length: int,
    ) -> int:
        for key in ("max_completion_tokens", "max_tokens"):
            value = body.get(key)
            if value is None:
                continue
            if type(value) is not int or value < 0:
                raise ValueError(f"{key} must be a non-negative integer")
            return value
        return max(0, context_length - input_tokens)

    def inspect(
        self,
        body: Mapping[str, JsonInput],
        *,
        context_length: int,
    ) -> ModelRequestTokenBudget:
        if not isinstance(body, Mapping):
            raise TypeError("model request tokenization body must be a mapping")
        if type(context_length) is not int or context_length <= 0:
            raise ValueError("model request tokenization context_length must be positive")
        url = self.binding.base_url.rstrip("/") + "/tokenize"
        # Tokenization is a public wire boundary. Model request bodies are
        # deeply frozen inside the kernel, so materialize them through the
        # strict finite-JSON boundary instead of relying on stdlib json to
        # understand platform Mapping implementations.
        raw = strict_finite_json_bytes(self._payload(body))
        cache_key = sha256(raw).hexdigest()
        def fetch() -> tuple[int, int]:
            try:
                response = self.transport.post_json(
                    url,
                    raw,
                    timeout_s=float(self.binding.timeout_s),
                )
            except ModelEndpointError as exc:
                raise RuntimeError("qualified model tokenization request failed") from exc
            if not 200 <= response.status_code < 300:
                raise RuntimeError(
                    "qualified model tokenization endpoint returned "
                    f"HTTP {response.status_code}"
                )
            document = response.body
            if not isinstance(document, Mapping):
                raise TypeError(
                    "qualified model tokenization response must be an object"
                )
            count = document.get("count")
            max_model_len = document.get("max_model_len")
            if type(count) is not int or count < 0:
                raise ValueError(
                    "qualified model tokenization response count is invalid"
                )
            if type(max_model_len) is not int or max_model_len <= 0:
                raise ValueError(
                    "qualified model tokenization response max_model_len is invalid"
                )
            return count, max_model_len

        count, max_model_len = self.cache.get_or_create(cache_key, fetch)
        if max_model_len != self.binding.model.context_length:
            raise ValueError(
                "qualified model tokenization endpoint context identity drift"
            )
        if context_length != self.binding.model.context_length:
            raise ValueError(
                "model request context_length drifted from qualified model identity"
            )
        return ModelRequestTokenBudget(
            tokenization_digest=self.identity.digest(),
            input_tokens=count,
            requested_output_tokens=self._requested_output_tokens(
                body,
                input_tokens=count,
                context_length=context_length,
            ),
            context_length=context_length,
        )


class QualifiedEndpointTokenizationProvider(ModelRequestTokenizationProviderPort):
    def __init__(
        self,
        binding: QualifiedModelEndpointBinding,
        *,
        transport: ModelJsonHttpClientPort,
        cache_entries: int = 4096,
        cache: ExactModelTokenizationCache | None = None,
    ) -> None:
        if not isinstance(binding, QualifiedModelEndpointBinding):
            raise TypeError(
                "qualified tokenization provider requires QualifiedModelEndpointBinding"
            )
        if not isinstance(transport, ModelJsonHttpClientPort):
            raise TypeError(
                "qualified tokenization provider requires ModelJsonHttpClientPort"
            )
        self._binding = binding
        self._transport = transport
        self._cache = (
            ExactModelTokenizationCache(cache_entries)
            if cache is None
            else cache
        )
        if not isinstance(self._cache, ExactModelTokenizationCache):
            raise TypeError(
                "qualified tokenization provider cache must be ExactModelTokenizationCache"
            )
        self._implementation_digest = canonical_digest(
            {
                "implementation": "openai-compatible-qualified-tokenization.v2",
                "request_protocol": "vllm.openai.tokenize.v1",
            }
        )

    def bind(
        self,
        *,
        model: ImmutableModelIdentity,
        model_stack_digest: str,
        tokenizer_sha256: str,
        chat_template_sha256: str | None,
    ) -> ModelRequestTokenizationPort:
        if model != self._binding.model:
            raise ValueError("qualified tokenization requested model is not bound")
        if model_stack_digest != self._binding.model_stack_digest:
            raise ValueError("qualified tokenization requested stack is not bound")
        if tokenizer_sha256 != self._binding.tokenizer_sha256:
            raise ValueError("qualified tokenization requested tokenizer is not bound")
        if chat_template_sha256 != self._binding.chat_template_sha256:
            raise ValueError(
                "qualified tokenization requested chat template is not bound"
            )
        identity = ModelRequestTokenizationIdentity(
            model=model,
            model_stack_digest=model_stack_digest,
            tokenizer_sha256=tokenizer_sha256,
            chat_template_sha256=chat_template_sha256,
            implementation_digest=self._implementation_digest,
            request_protocol="vllm.openai.tokenize.v1",
        )
        return OpenAICompatibleQualifiedTokenization(
            self._binding,
            identity,
            self._transport,
            self._cache,
        )


__all__ = [
    "ExactModelTokenizationCache",
    "OpenAICompatibleQualifiedTokenization",
    "QualifiedEndpointTokenizationProvider",
]
