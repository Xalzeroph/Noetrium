from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math


@dataclass(frozen=True, slots=True)
class PromptSection:
    section_id: str
    text: str
    priority: int


@dataclass(frozen=True, slots=True)
class PromptSpec:
    prompt_id: str
    role: str
    version: str
    model_family: str
    output_schema: str
    sections: tuple[PromptSection, ...]
    temperature: float
    top_p: float
    max_output_tokens: int

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (self.prompt_id, self.role, self.version, self.model_family, self.output_schema)):
            raise ValueError("prompt spec identity fields must be non-empty")
        if type(self.sections) is not tuple or not self.sections:
            raise ValueError("prompt spec requires at least one section")
        for field in ("temperature", "top_p"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"prompt spec {field} must be finite")
        if self.temperature < 0:
            raise ValueError("prompt spec temperature must be non-negative")
        if not 0 < self.top_p <= 1:
            raise ValueError("prompt spec top_p must be within (0, 1]")
        if type(self.max_output_tokens) is not int or self.max_output_tokens <= 0:
            raise ValueError("prompt spec max_output_tokens must be positive")

    def compile(self) -> str:
        return "\n\n".join(s.text.strip() for s in sorted(self.sections, key=lambda x: (x.priority, x.section_id))) + "\n"

    def bundle_digest(self) -> str:
        payload = {
            "prompt_id": self.prompt_id, "role": self.role, "version": self.version,
            "model_family": self.model_family, "output_schema": self.output_schema,
            "temperature": self.temperature, "top_p": self.top_p,
            "max_output_tokens": self.max_output_tokens,
            "text": self.compile(),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
