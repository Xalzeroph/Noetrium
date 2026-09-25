from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Mapping, Protocol

from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity, JsonObject, freeze_json


@dataclass(frozen=True, slots=True)
class PromptDynamicBlock:
    """Project-owned dynamic evidence expressed in the prompt API vocabulary."""

    kind: str
    content: str
    source_digest: str
    sequence: int


@dataclass(frozen=True, slots=True)
class PromptBodyContext:
    """Compiled prompt facts exposed to a project body-shaping function."""

    prompt_id: str
    prompt_digest: str
    role: str
    model_id: str
    output_schema: str
    compiled_text: str
    temperature: float
    top_p: float
    max_output_tokens: int

    def __post_init__(self) -> None:
        for field in ("temperature", "top_p"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"prompt body context {field} must be finite")
        if self.temperature < 0 or not 0 < self.top_p <= 1:
            raise ValueError("prompt body context sampling parameters are invalid")
        if type(self.max_output_tokens) is not int or self.max_output_tokens <= 0:
            raise ValueError("prompt body context max_output_tokens must be positive")


PromptRequestBodyBuilder = Callable[[PromptBodyContext], JsonObject]


@dataclass(frozen=True, slots=True)
class PromptBoundRequest:
    request: ModelRequestEnvelope
    body: JsonObject
    prompt_generation_id: str
    prompt_id: str
    prompt_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.body, Mapping):
            raise TypeError("prompt-bound request body must be a mapping")
        object.__setattr__(self, "body", freeze_json(self.body))


class PromptRequestBindingPort(Protocol):
    """Frozen prompt-to-model-request port consumed by project composition."""

    def build(
        self,
        *,
        blocks: tuple[PromptDynamicBlock, ...],
        context_length: int,
        request_id: str,
        context: ExecutionContext,
        model: ImmutableModelIdentity,
        body_builder: PromptRequestBodyBuilder,
        source_artifact_refs: tuple[str, ...] = (),
        source_state_refs: tuple[str, ...] = (),
    ) -> PromptBoundRequest: ...


__all__ = [
    "PromptBoundRequest",
    "PromptBodyContext",
    "PromptDynamicBlock",
    "PromptRequestBindingPort",
    "PromptRequestBodyBuilder",
]
