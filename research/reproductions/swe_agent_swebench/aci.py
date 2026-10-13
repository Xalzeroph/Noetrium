from __future__ import annotations

from dataclasses import dataclass
from .fidelity import SWE_AGENT_07_FIDELITY

@dataclass(frozen=True, slots=True)
class SweAgentTurn:
    discussion: str
    command: str

    def __post_init__(self) -> None:
        if not isinstance(self.discussion, str) or not self.discussion.strip():
            raise ValueError("SWE-agent turn requires discussion")
        if not isinstance(self.command, str) or not self.command.strip():
            raise ValueError("SWE-agent turn requires exactly one command")
        normalized = self.command.strip()
        if "\n" in normalized or "\r" in normalized:
            raise ValueError("SWE-agent 0.7 command field must contain one command")
        object.__setattr__(self, "discussion", self.discussion.strip())
        object.__setattr__(self, "command", normalized)

    @property
    def submit_requested(self) -> bool:
        return self.command == SWE_AGENT_07_FIDELITY.submit_command

__all__ = ("SweAgentTurn",)
