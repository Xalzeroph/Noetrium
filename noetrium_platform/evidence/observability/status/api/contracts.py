from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

_REASON_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")


class HealthState(StrEnum):
    READY = "ready"
    DEGRADED_EVIDENCE = "degraded_evidence"
    DEGRADED_OPERATIONAL = "degraded_operational"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SubsystemSnapshot:
    subsystem: str
    state: HealthState
    summary: str
    evidence: tuple[str, ...] = ()
    failure_id: str | None = None
    next_commands: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.subsystem:
            raise ValueError("subsystem identity required")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("status reason codes must be unique")
        if any(not _REASON_CODE_RE.fullmatch(code) for code in self.reason_codes):
            raise ValueError("status reason code must be a stable machine identifier")


@dataclass(frozen=True, slots=True)
class PlatformStatus:
    snapshots: tuple[SubsystemSnapshot, ...]

    @property
    def failed(self) -> tuple[SubsystemSnapshot, ...]:
        return tuple(s for s in self.snapshots if s.state is HealthState.FAILED)

    @property
    def degraded(self) -> tuple[SubsystemSnapshot, ...]:
        return tuple(
            s for s in self.snapshots
            if s.state in {HealthState.DEGRADED_EVIDENCE, HealthState.DEGRADED_OPERATIONAL}
        )

    def to_dict(self) -> dict[str, object]:
        if self.failed:
            overall = "failed"
        elif any(s.state is HealthState.DEGRADED_EVIDENCE for s in self.snapshots):
            overall = "degraded_evidence"
        elif any(s.state is HealthState.DEGRADED_OPERATIONAL for s in self.snapshots):
            overall = "degraded_operational"
        elif any(s.state is HealthState.UNKNOWN for s in self.snapshots):
            overall = "unknown"
        else:
            overall = "ready"
        return {
            "schema_version": "platform-status.v2",
            "status": overall,
            "subsystems": [
                {
                    "subsystem": s.subsystem,
                    "state": s.state.value,
                    "summary": s.summary,
                    "evidence": list(s.evidence),
                    "failure_id": s.failure_id,
                    "next_commands": list(s.next_commands),
                    "reason_codes": list(s.reason_codes),
                }
                for s in self.snapshots
            ],
        }


__all__ = ["HealthState", "PlatformStatus", "SubsystemSnapshot"]
