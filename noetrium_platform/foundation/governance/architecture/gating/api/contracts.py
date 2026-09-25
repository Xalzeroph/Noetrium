from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class GateSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class GateRequest:
    subject_id: str
    root: Path
    phase: str = "verification"

    def __post_init__(self) -> None:
        if not self.subject_id.strip():
            raise ValueError("gate subject_id must be non-empty")
        if not self.phase.strip():
            raise ValueError("gate phase must be non-empty")


@dataclass(frozen=True, slots=True)
class GateFinding:
    gate_id: str
    severity: GateSeverity
    code: str
    detail: str

    @property
    def is_failure(self) -> bool:
        return self.severity is GateSeverity.ERROR


@dataclass(frozen=True, slots=True)
class GateReport:
    gate_id: str
    findings: tuple[GateFinding, ...] = ()
    children: tuple["GateReport", ...] = ()

    @property
    def all_findings(self) -> tuple[GateFinding, ...]:
        return self.findings + tuple(
            finding
            for child in self.children
            for finding in child.all_findings
        )

    @property
    def passed(self) -> bool:
        return not any(finding.is_failure for finding in self.all_findings)


__all__ = ["GateFinding", "GateReport", "GateRequest", "GateSeverity"]
