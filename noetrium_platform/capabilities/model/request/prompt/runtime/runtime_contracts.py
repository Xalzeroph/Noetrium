from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class ActivePromptBundle:
    prompt_id: str
    role: str
    version: str
    digest: str
    text: str
    output_schema: str
    model_family: str
    temperature: float
    top_p: float
    max_output_tokens: int

    def __post_init__(self) -> None:
        for field in ("temperature", "top_p"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"active prompt {field} must be finite")
        if self.temperature < 0 or not 0 < self.top_p <= 1:
            raise ValueError("active prompt sampling parameters are invalid")
        if type(self.max_output_tokens) is not int or self.max_output_tokens <= 0:
            raise ValueError("active prompt max_output_tokens must be positive")


@dataclass(frozen=True, slots=True)
class PromptResolution:
    generation_id: str
    bundle: ActivePromptBundle
