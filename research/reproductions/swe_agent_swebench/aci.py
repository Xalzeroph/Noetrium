from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from noetrium.contracts.systems.participant__capability import (
    CapabilityDescriptor,
    CapabilityRequest,
    GuardDecision,
    GuardVerdict,
)


@dataclass(frozen=True, slots=True)
class SWEAgentCurrentCommandPolicy:
    """Method-owned ACI command filter from the audited current SWE-agent reference.

    Noetrium owns the generic guard/approval/effect machinery. The concrete
    command vocabulary and blocking rules remain reproduction semantics and can
    evolve independently without becoming Research OS policy.
    """

    blocked_prefixes: tuple[str, ...] = (
        "vim",
        "vi",
        "emacs",
        "nano",
        "nohup",
        "gdb",
        "less",
        "tail -f",
        "python -m venv",
        "make",
    )
    blocked_standalone: tuple[str, ...] = (
        "python",
        "python3",
        "ipython",
        "bash",
        "sh",
        "/bin/bash",
        "/bin/sh",
        "nohup",
        "vi",
        "vim",
        "emacs",
        "nano",
        "su",
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
        if name in conditional and re.search(conditional[name], action) is None:
            return True
        return False


SWE_AGENT_CURRENT_COMMAND_POLICY = SWEAgentCurrentCommandPolicy()


class SWEAgentCommandGuard:
    """Adapter from SWE-agent ACI policy to Noetrium's generic capability guard."""

    guard_id = "reproduction.swe-agent.command-policy.v1"

    def __init__(
        self,
        policy: SWEAgentCurrentCommandPolicy = SWE_AGENT_CURRENT_COMMAND_POLICY,
        *,
        capability_id: str = "software.command",
    ) -> None:
        if not isinstance(policy, SWEAgentCurrentCommandPolicy):
            raise TypeError("SWE-agent guard requires SWEAgentCurrentCommandPolicy")
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise ValueError("SWE-agent command capability_id is required")
        self._policy = policy
        self._capability_id = capability_id

    def evaluate(
        self,
        descriptor: CapabilityDescriptor,
        request: CapabilityRequest,
    ) -> GuardDecision:
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


__all__ = [
    "SWE_AGENT_CURRENT_COMMAND_POLICY",
    "SWEAgentCommandGuard",
    "SWEAgentCurrentCommandPolicy",
]
