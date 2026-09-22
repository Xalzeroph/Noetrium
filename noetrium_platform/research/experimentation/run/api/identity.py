from __future__ import annotations

from dataclasses import asdict, dataclass

from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind


@dataclass(frozen=True, slots=True)
class RunIdentity:
    run_id: str
    session_id: str
    trace_id: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"RunIdentity.{name} must be non-empty")

    @property
    def scope(self) -> ScopeIdentity:
        return ScopeIdentity(ScopeKind.RUN, self.run_id)

    def digest(self) -> str:
        return canonical_digest(self)

    def cycle(self, *, decision_cycle_id: str, task_id: str) -> DecisionCycleIdentity:
        return DecisionCycleIdentity(
            self.run_id,
            decision_cycle_id,
            self.session_id,
            task_id,
            self.trace_id,
        )


__all__ = ["RunIdentity"]
