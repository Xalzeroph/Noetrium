from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.infrastructure.reliability.diagnostics.api import DiagnosticEvidencePort


@dataclass(frozen=True, slots=True)
class EvidenceVerificationReport:
    valid: bool
    rows: dict[str, int]
    tail_hashes: dict[str, str]


class EvidenceVerifier:
    def __init__(self, evidence: DiagnosticEvidencePort) -> None:
        self.evidence = evidence

    def verify(self) -> EvidenceVerificationReport:
        result = self.evidence.verify_authoritative()
        return EvidenceVerificationReport(
            valid=True,
            rows={name: count for name, (count, _) in result.items()},
            tail_hashes={name: tail for name, (_, tail) in result.items()},
        )
