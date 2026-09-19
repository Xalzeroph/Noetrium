from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace

from noetrium.contracts.systems.participant__capability import (
    CapabilityDescriptor,
    CapabilityRequest,
    GuardDecision,
    GuardVerdict,
)
from .fidelity import SWE_AGENT_07_FIDELITY


@dataclass(frozen=True, slots=True)
class SWEAgentCurrentCommandPolicy:
    """Method-owned ACI command filter from the audited current SWE-agent reference."""

    blocked_prefixes: tuple[str, ...] = (
        "vim", "vi", "emacs", "nano", "nohup", "gdb", "less", "tail -f", "python -m venv", "make",
    )
    blocked_standalone: tuple[str, ...] = (
        "python", "python3", "ipython", "bash", "sh", "/bin/bash", "/bin/sh", "nohup", "vi", "vim", "emacs", "nano", "su",
    )
    block_unless_regex: tuple[tuple[str, str], ...] = (
        ("radare2", r"\b(?:radare2)\b.*\s+-c\s+.*"),
        ("r2", r"\b(?:radare2)\b.*\s+-c\s+.*"),
    )

    def should_block(self, command: str) -> bool:
        if not isinstance(command, str):
            raise TypeError("SWE-agent command must be text")
        action = command.strip()
        if not action:
            return False
        if any(action.startswith(prefix) for prefix in self.blocked_prefixes):
            return True
        if action in self.blocked_standalone:
            return True
        name = action.split()[0]
        conditional = dict(self.block_unless_regex)
        return name in conditional and re.search(conditional[name], action) is None


SWE_AGENT_CURRENT_COMMAND_POLICY = SWEAgentCurrentCommandPolicy()


class SWEAgentCommandGuard:
    """Adapter from SWE-agent ACI policy to Noetrium's generic capability guard."""

    guard_id = "reproduction.swe-agent.command-policy.v1"

    def __init__(self, policy: SWEAgentCurrentCommandPolicy = SWE_AGENT_CURRENT_COMMAND_POLICY, *, capability_id: str = "software.command") -> None:
        if not isinstance(policy, SWEAgentCurrentCommandPolicy):
            raise TypeError("SWE-agent guard requires SWEAgentCurrentCommandPolicy")
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise ValueError("SWE-agent command capability_id is required")
        self._policy = policy
        self._capability_id = capability_id

    def evaluate(self, descriptor: CapabilityDescriptor, request: CapabilityRequest) -> GuardDecision:
        if descriptor.capability_id != self._capability_id or request.capability_id != self._capability_id:
            return GuardDecision(self.guard_id, GuardVerdict.ABSTAIN)
        payload = request.payload
        if not isinstance(payload, Mapping):
            return GuardDecision(self.guard_id, GuardVerdict.DENY, "malformed_software_command")
        command = payload.get("command")
        if not isinstance(command, str) or not command.strip():
            return GuardDecision(self.guard_id, GuardVerdict.DENY, "malformed_software_command")
        if self._policy.should_block(command):
            return GuardDecision(self.guard_id, GuardVerdict.DENY, "unsupported_interactive_or_blocked_command")
        return GuardDecision(self.guard_id, GuardVerdict.ALLOW)


@dataclass(frozen=True, slots=True)
class SweAgentTurn:
    """Paper-era method-owned ACI turn; execution/effects remain Research Agent OS-owned."""

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
    """Enforce command-to-observation alternation without owning shell state."""

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
    return observations[-SWE_AGENT_07_FIDELITY.visible_observation_history :]


__all__ = [
    "SWE_AGENT_CURRENT_COMMAND_POLICY", "SWEAgentCommandGuard", "SWEAgentCurrentCommandPolicy",
    "SweAgentAciState", "SweAgentTurn", "visible_observation_suffix",
]