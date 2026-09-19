from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.model.api import (
    ModelRequestTokenBudget,
    ModelRequestTokenizationIdentity,
)
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity, JsonInput, canonical_digest


class FixedModelRequestTokenization:
    def __init__(
        self,
        *,
        model: ImmutableModelIdentity,
        model_stack_digest: str,
        tokenizer_sha256: str,
        chat_template_sha256: str | None,
        input_tokens: int,
    ) -> None:
        self.identity = ModelRequestTokenizationIdentity(
            model=model,
            model_stack_digest=model_stack_digest,
            tokenizer_sha256=tokenizer_sha256,
            chat_template_sha256=chat_template_sha256,
            implementation_digest=canonical_digest({"test_tokenization": "fixed.v1"}),
            request_protocol="test.fixed-tokenization.v1",
        )
        if type(input_tokens) is not int or input_tokens < 0:
            raise ValueError("fixed model request input_tokens must be non-negative")
        self._input_tokens = input_tokens

    def inspect(
        self,
        body: Mapping[str, JsonInput],
        *,
        context_length: int,
    ) -> ModelRequestTokenBudget:
        raw_output = body.get("max_tokens", body.get("max_output_tokens", 0))
        if type(raw_output) is not int or raw_output < 0:
            raise ValueError("test request output reservation must be a non-negative integer")
        return ModelRequestTokenBudget(
            tokenization_digest=self.identity.digest(),
            input_tokens=self._input_tokens,
            requested_output_tokens=raw_output,
            context_length=context_length,
        )


class FixedModelRequestTokenizationProvider:
    def __init__(self, *, input_tokens: int = 1) -> None:
        if type(input_tokens) is not int or input_tokens < 0:
            raise ValueError("fixed tokenization provider input_tokens must be non-negative")
        self._input_tokens = input_tokens

    def bind(
        self,
        *,
        model: ImmutableModelIdentity,
        model_stack_digest: str,
        tokenizer_sha256: str,
        chat_template_sha256: str | None,
    ) -> FixedModelRequestTokenization:
        return FixedModelRequestTokenization(
            model=model,
            model_stack_digest=model_stack_digest,
            tokenizer_sha256=tokenizer_sha256,
            chat_template_sha256=chat_template_sha256,
            input_tokens=self._input_tokens,
        )


__all__ = ["FixedModelRequestTokenization", "FixedModelRequestTokenizationProvider"]
