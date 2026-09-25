from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import JsonObject, freeze_json


class AgentCompletionDisposition(StrEnum):
    CONTINUE = "continue"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AgentCompletionDecision:
    """Typed episode/objective terminal decision.

    ``CONTINUE`` means the Agent Turn may act again. ``SUCCEEDED`` and
    ``FAILED`` are both terminal. This deliberately separates liveness from
    scientific/task success so an environment may terminate unsuccessfully
    without the OS issuing actions into a dead episode.
    """

    disposition: AgentCompletionDisposition
    reason: str
    evidence: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, AgentCompletionDisposition):
            raise TypeError("agent completion disposition must be AgentCompletionDisposition")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("agent completion decision reason is required")
        if not isinstance(self.evidence, Mapping):
            raise TypeError("agent completion evidence must be a mapping")
        object.__setattr__(self, "evidence", freeze_json(self.evidence))

    @property
    def terminal(self) -> bool:
        return self.disposition is not AgentCompletionDisposition.CONTINUE

    @property
    def success(self) -> bool | None:
        if self.disposition is AgentCompletionDisposition.CONTINUE:
            return None
        return self.disposition is AgentCompletionDisposition.SUCCEEDED

    @classmethod
    def continue_(cls, reason: str = "objective_not_terminal") -> "AgentCompletionDecision":
        return cls(AgentCompletionDisposition.CONTINUE, reason)

    @classmethod
    def succeeded(
        cls, reason: str = "objective_satisfied", *, evidence: JsonObject | None = None
    ) -> "AgentCompletionDecision":
        return cls(AgentCompletionDisposition.SUCCEEDED, reason, evidence or {})

    @classmethod
    def failed(
        cls, reason: str = "objective_terminal_failure", *, evidence: JsonObject | None = None
    ) -> "AgentCompletionDecision":
        return cls(AgentCompletionDisposition.FAILED, reason, evidence or {})


__all__ = ["AgentCompletionDecision", "AgentCompletionDisposition"]
