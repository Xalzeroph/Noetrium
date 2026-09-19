from __future__ import annotations

from pathlib import Path

from .source_scan import SourceInvariantViolation, imports, violation


def audit_composition_family_firewall(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    composition = root / "noetrium_platform" / "composition"
    checks = (
        (composition / "context_action.py", "composition_context_action_firewall", (
            "noetrium_platform.capabilities.participant.agent.api", "noetrium_platform.capabilities.participant.capability.api", "noetrium_platform.composition.agent_turn",
            "noetrium_platform.composition.participants.agent", "noetrium_platform.composition.participants.capability",
            "noetrium_platform.composition.registries.agent", "noetrium_platform.composition.registries.capability",
            "noetrium_platform.research.execution.workflow.implementations.agent_turn",
        )),
        (composition / "agent_turn.py", "composition_agent_turn_firewall", (
            "noetrium_platform.capabilities.environment.runtime.api", "noetrium_platform.capabilities.participant.method.api", "noetrium_platform.composition.context_action",
            "noetrium_platform.composition.participants.environment", "noetrium_platform.composition.participants.method",
            "noetrium_platform.composition.registries.environment", "noetrium_platform.composition.registries.method",
            "noetrium_platform.research.execution.workflow.implementations.context_action",
        )),
    )
    for path, invariant, forbidden in checks:
        if not path.exists():
            continue
        for module, line in imports(path):
            if any(module.startswith(prefix) for prefix in forbidden):
                rows.append(violation(root, path, invariant, line, f"composition family imports unrelated domain authority {module}"))

    bridge_checks = (
        (composition / "participants" / "method.py", "participant_method_bridge_firewall", ("noetrium_platform.capabilities.environment.runtime.api", "noetrium_platform.capabilities.participant.agent.api", "noetrium_platform.capabilities.participant.capability.api")),
        (composition / "participants" / "environment.py", "participant_environment_bridge_firewall", ("noetrium_platform.capabilities.participant.method.api", "noetrium_platform.capabilities.participant.agent.api", "noetrium_platform.capabilities.participant.capability.api")),
        (composition / "participants" / "agent.py", "participant_agent_bridge_firewall", ("noetrium_platform.capabilities.participant.method.api", "noetrium_platform.capabilities.environment.runtime.api", "noetrium_platform.capabilities.participant.capability.api")),
        (composition / "participants" / "capability.py", "participant_capability_bridge_firewall", ("noetrium_platform.capabilities.participant.method.api", "noetrium_platform.capabilities.environment.runtime.api", "noetrium_platform.capabilities.participant.agent.api")),
        (composition / "participants" / "generic.py", "participant_generic_bridge_firewall", ("noetrium_platform.capabilities.participant.method.api", "noetrium_platform.capabilities.environment.runtime.api", "noetrium_platform.capabilities.participant.agent.api", "noetrium_platform.capabilities.participant.capability.api")),
    )
    for path, invariant, forbidden in bridge_checks:
        if not path.exists():
            continue
        for module, line in imports(path):
            if any(module.startswith(prefix) for prefix in forbidden):
                rows.append(violation(root, path, invariant, line, f"participant bridge imports unrelated specialized ABI {module}"))
    return rows


__all__ = ["audit_composition_family_firewall"]
