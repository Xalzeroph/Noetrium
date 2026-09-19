from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    ImmutableModelIdentity,
    JsonInput,
    canonical_digest,
    require_sha256,
)


@dataclass(frozen=True, slots=True)
class ModelRequestTokenizationIdentity:
    """Exact request-tokenization semantics bound to one qualified model stack."""

    model: ImmutableModelIdentity
    model_stack_digest: str
    tokenizer_sha256: str
    chat_template_sha256: str | None
    implementation_digest: str
    request_protocol: str

    def __post_init__(self) -> None:
        if not isinstance(self.model, ImmutableModelIdentity):
            raise TypeError("model request tokenization model must be ImmutableModelIdentity")
        if self.model.tokenizer_revision is None or not self.model.tokenizer_revision.strip():
            raise ValueError("exact model request tokenization requires tokenizer_revision")
        require_sha256(self.model_stack_digest, "model request tokenization model_stack_digest")
        require_sha256(self.tokenizer_sha256, "model request tokenization tokenizer_sha256")
        if self.chat_template_sha256 is not None:
            require_sha256(self.chat_template_sha256, "model request tokenization chat_template_sha256")
        require_sha256(self.implementation_digest, "model request tokenization implementation_digest")
        if not isinstance(self.request_protocol, str) or not self.request_protocol.strip():
            raise ValueError("model request tokenization request_protocol is required")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ModelRequestTokenBudget:
    tokenization_digest: str
    input_tokens: int
    requested_output_tokens: int
    context_length: int

    def __post_init__(self) -> None:
        require_sha256(self.tokenization_digest, "model request token budget tokenization_digest")
        for name in ("input_tokens", "requested_output_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"model request token budget {name} must be non-negative")
        if type(self.context_length) is not int or self.context_length <= 0:
            raise ValueError("model request token budget context_length must be positive")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.requested_output_tokens

    @property
    def fits(self) -> bool:
        return self.total_tokens <= self.context_length

    def digest(self) -> str:
        return canonical_digest(self)


class ModelRequestContextExceeded(RuntimeError):
    def __init__(self, budget: ModelRequestTokenBudget) -> None:
        self.budget = budget
        super().__init__(
            "model request exceeds qualified context: "
            f"input={budget.input_tokens} output={budget.requested_output_tokens} "
            f"context={budget.context_length}"
        )


@runtime_checkable
class ModelRequestTokenizationPort(Protocol):
    @property
    def identity(self) -> ModelRequestTokenizationIdentity: ...

    def inspect(
        self,
        body: Mapping[str, JsonInput],
        *,
        context_length: int,
    ) -> ModelRequestTokenBudget: ...


@runtime_checkable
class ModelRequestTokenizationProviderPort(Protocol):
    def bind(
        self,
        *,
        model: ImmutableModelIdentity,
        model_stack_digest: str,
        tokenizer_sha256: str,
        chat_template_sha256: str | None,
    ) -> ModelRequestTokenizationPort: ...


__all__ = [
    "ModelRequestContextExceeded",
    "ModelRequestTokenBudget",
    "ModelRequestTokenizationIdentity",
    "ModelRequestTokenizationPort",
    "ModelRequestTokenizationProviderPort",
]
