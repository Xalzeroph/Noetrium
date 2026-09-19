from __future__ import annotations

from dataclasses import dataclass
import math

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .publication_common import sha256_bytes
from .qualification import PromptQualification


@dataclass(frozen=True, slots=True)
class PromptPromotionEvidence:
    generation_id:str
    generation_payload_sha256:str
    canary_suite_digest:str
    qualifications:tuple[PromptQualification,...]
    model_resume_key:tuple[object,...]
    objective_evidence_digest:str
    created_at:float

    def __post_init__(self) -> None:
        if (
            isinstance(self.created_at, bool)
            or not isinstance(self.created_at, (int, float))
            or not math.isfinite(float(self.created_at))
            or self.created_at < 0
        ):
            raise ValueError("prompt promotion created_at must be finite and non-negative")

    def digest(self)->str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class PromptPromotionRecord:
    generation_id:str
    generation_payload_sha256:str
    promotion_evidence_digest:str
    previous_generation_id:str|None
    activated_at:float

    def __post_init__(self) -> None:
        if (
            isinstance(self.activated_at, bool)
            or not isinstance(self.activated_at, (int, float))
            or not math.isfinite(float(self.activated_at))
            or self.activated_at < 0
        ):
            raise ValueError("prompt promotion activated_at must be finite and non-negative")
