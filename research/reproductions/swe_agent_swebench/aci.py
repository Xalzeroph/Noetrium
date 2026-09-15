from __future__ import annotations

from dataclasses import dataclass, replace

from .fidelity import SWE_AGENT_07_FIDELITY


@dataclass(frozen=True, slots=True)
class SweAgentTurn:
    """Method-owned ACI turn; execution/effects remain Research Agent OS-owned."""

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


@dataclass(frozen=True, slots=True)
class SweAgentAciState:
    """Enforce command→observation alternation without owning shell state."""

    turn_index: int = 0
    awaiting_observation: bool = False

    def issue(self, turn: SweAgentTurn) -> "SweAgentAciState":
        if not isinstance(turn, SweAgentTurn):
            raise TypeError("SWE-agent ACI requires a typed turn")
        if self.awaiting_observation:
            raise ValueError("SWE-agent must wait for feedback before issuing another command")
        return replace(self, awaiting_observation=True)

    def observe(self, observation: str) -> "SweAgentAciState":
        if not self.awaiting_observation:
            raise ValueError("SWE-agent cannot consume feedback without a pending command")
        if not isinstance(observation, str):
            raise TypeError("SWE-agent observation must be text")
        return SweAgentAciState(self.turn_index + 1, False)


def visible_observation_suffix(observations: tuple[str, ...]) -> tuple[str, ...]:
    if any(not isinstance(item, str) for item in observations):
        raise TypeError("SWE-agent observation history must be text")
    return observations[-SWE_AGENT_07_FIDELITY.visible_observation_history:]


__all__ = ["SweAgentAciState", "SweAgentTurn", "visible_observation_suffix"]
