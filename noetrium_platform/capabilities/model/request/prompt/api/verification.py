from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ActivePromptVerificationEvidence:
    generation_id: str
    generation_payload_sha256: str
    promotion_evidence_digest: str


class ActivePromptEvidenceReadPort(Protocol):
    """Read-only frozen evidence exported by the prompt subsystem."""

    def read_active_verification_evidence(self) -> ActivePromptVerificationEvidence: ...


class PromptVerificationIntegrityError(RuntimeError):
    pass


__all__ = [
    "ActivePromptEvidenceReadPort",
    "ActivePromptVerificationEvidence",
    "PromptVerificationIntegrityError",
]
