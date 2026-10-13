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
from noetrium_platform.capabilities.model.serving.api.admission import ModelAdmissionPort
from noetrium_platform.capabilities.model.serving.endpoint.runtime.request_retry import ModelRequestRetryPolicy
from noetrium_platform.foundation.kernel.kernel import (
    ImmutableModelIdentity,
    JsonInput,
    canonical_digest,
    strict_finite_json_bytes,
    blocking_wait,
)
from noetrium_platform.foundation.kernel.concurrency.api import SingleFlightCache


class ExactModelTokenizationCache:
    """Bounded exact cache using the platform's sole single-flight primitive."""

    def __init__(self, max_entries: int) -> None:
        self._rows: SingleFlightCache[
            ModelRequestTokenBudget
        ] = SingleFlightCache(
            max_entries=max_entries
        )

    def get_or_create(
        self,
        key: str,
        builder,
    ) -> ModelRequestTokenBudget:
        return self._rows.get_or_create(key, builder)

    def __len__(self) -> int:
        return len(self._rows)


@dataclass(frozen=True, slots=True)
class OpenAICompatibleQualifiedTokenization:
    binding: QualifiedModelEndpointBinding
    identity: ModelRequestTokenizationIdentity
    transport: ModelJsonHttpClientPort
    admission: ModelAdmissionPort
    cache: ExactModelTokenizationCache = field(
        default_factory=lambda: ExactModelTokenizationCache(4096),
        repr=False,
        compare=False,
    )
    retry_policy: ModelRequestRetryPolicy = field(
        default_factory=lambda: ModelRequestRetryPolicy(max_attempts=3),
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
        if not callable(getattr(self.admission, "acquire", None)):
            raise TypeError("qualified tokenization requires model admission authority")
        if not isinstance(self.cache, ExactModelTokenizationCache):
            raise TypeError("qualified tokenization requires exact cache authority")
        if not isinstance(self.retry_policy, ModelRequestRetryPolicy):
            raise TypeError("qualified tokenization retry policy has invalid type")

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
    def _transport_timeout_seconds(
        binding: QualifiedModelEndpointBinding,
    ) -> float:
        """Return a finite physical /tokenize transport budget.

        Tokenization queue/admission waiting is Resource Authority time and is
        intentionally excluded. Once physical HTTP dispatch begins, however,
        qualified service evidence must bound liveness. An explicit route
        timeout remains authoritative; otherwise the frozen model context and
        measured prefill service rate provide a conservative full-context
        service window. Measured return TTFT may only widen that window.
        """
        if binding.timeout_s is not None:
            return float(binding.timeout_s)
        service_tokens = max(
            int(binding.model.context_length),
            int(binding.max_prefill_queued_tokens),
        )
        timeout = service_tokens / float(binding.prefill_input_tokens_per_second)
        ttft = binding.preemptive_return_ttft_p99_seconds
        if ttft is not None:
            timeout = max(timeout, float(ttft))
        if timeout <= 0.0:
            raise RuntimeError(
                "qualified tokenization transport budget must be positive"
            )
        return timeout

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
            if type(value) is not int or value <= 0:
                raise ValueError(f"{key} must be a positive integer")
            return value
        raise ValueError(
            "scientific generation request requires explicit max_tokens or "
            "max_completion_tokens; implicit full-context output budgets are forbidden"
        )

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
        def fetch() -> ModelRequestTokenBudget:
            # Cache misses share the exact single-flight and admission
            # authorities with generation. Transient transport errors retain
            # their typed retryability instead of becoming RuntimeError.
            response = None
            for attempt in range(1, self.retry_policy.max_attempts + 1):
                lease = self.admission.acquire(
                    timeout_seconds=None,
                    owner_id="tokenization:" + self.identity.digest(),
                )
                try:
                    response = self.transport.post_json(
                        url,
                        raw,
                        timeout_s=self._transport_timeout_seconds(self.binding),
                    )
                except ModelEndpointError as exc:
                    can_retry = (
                        attempt < self.retry_policy.max_attempts
                        and exc.retryable
                        and exc.failure_kind in self.retry_policy.retryable_failure_kinds
                    )
                    if not can_retry:
                        raise
                    delay = self.retry_policy.wait_seconds(
                        attempt_number=attempt,
                        retry_after_seconds=exc.retry_after_seconds,
                    )
                else:
                    break
                finally:
                    lease.release()
                if delay > 0:
                    blocking_wait(delay)
            if response is None:
                raise RuntimeError("qualified tokenization exhausted without a response")
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
            tokens = document.get("tokens")
            if type(count) is not int or count < 0:
                raise ValueError(
                    "qualified model tokenization response count is invalid"
                )
            if type(max_model_len) is not int or max_model_len <= 0:
                raise ValueError(
                    "qualified model tokenization response max_model_len is invalid"
                )
            if not isinstance(tokens, (list, tuple)):
                raise ValueError(
                    "qualified model tokenization response tokens are invalid"
                )
            # ModelRequestTokenBudget is the single proof boundary for token
            # element domain and count agreement. Cache that proof object, not
            # a raw tuple that would have to be re-proven on every cache hit.
            return ModelRequestTokenBudget(
                tokenization_digest=self.identity.digest(),
                input_tokens=count,
                requested_output_tokens=0,
                context_length=max_model_len,
                input_token_ids=tuple(tokens),
            )

        base_budget = self.cache.get_or_create(
            cache_key,
            fetch,
        )
        if base_budget.context_length != self.binding.model.context_length:
            raise ValueError(
                "qualified model tokenization endpoint context identity drift"
            )
        if context_length != self.binding.model.context_length:
            raise ValueError(
                "model request context_length drifted from qualified model identity"
            )
        return base_budget.with_requested_output_tokens(
            self._requested_output_tokens(
                body,
                input_tokens=base_budget.input_tokens,
                context_length=context_length,
            )
        )


class QualifiedEndpointTokenizationProvider(ModelRequestTokenizationProviderPort):
    def __init__(
        self,
        binding: QualifiedModelEndpointBinding,
        *,
        transport: ModelJsonHttpClientPort,
        admission: ModelAdmissionPort,
        cache_entries: int = 4096,
        cache: ExactModelTokenizationCache | None = None,
        retry_policy: ModelRequestRetryPolicy | None = None,
    ) -> None:
        if not isinstance(binding, QualifiedModelEndpointBinding):
            raise TypeError(
                "qualified tokenization provider requires QualifiedModelEndpointBinding"
            )
        if not isinstance(transport, ModelJsonHttpClientPort):
            raise TypeError(
                "qualified tokenization provider requires ModelJsonHttpClientPort"
            )
        if not callable(getattr(admission, "acquire", None)):
            raise TypeError(
                "qualified tokenization provider requires model admission authority"
            )
        self._binding = binding
        self._transport = transport
        self._admission = admission
        self._cache = (
            ExactModelTokenizationCache(cache_entries)
            if cache is None
            else cache
        )
        self._retry_policy = (
            ModelRequestRetryPolicy(max_attempts=3)
            if retry_policy is None else retry_policy
        )
        if not isinstance(self._retry_policy, ModelRequestRetryPolicy):
            raise TypeError("qualified tokenization retry policy has invalid type")
        if not isinstance(self._cache, ExactModelTokenizationCache):
            raise TypeError(
                "qualified tokenization provider cache must be ExactModelTokenizationCache"
            )
        self._implementation_digest = canonical_digest(
            {
                "implementation": "openai-compatible-qualified-tokenization.v3",
                "request_protocol": "vllm.openai.tokenize.v1",
                "retry_policy_digest": self._retry_policy.policy_digest,
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
            self._admission,
            self._cache,
            self._retry_policy,
        )


__all__ = [
    "ExactModelTokenizationCache",
    "OpenAICompatibleQualifiedTokenization",
    "QualifiedEndpointTokenizationProvider",
]
