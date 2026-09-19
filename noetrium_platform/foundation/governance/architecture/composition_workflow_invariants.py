from __future__ import annotations

from pathlib import Path

from .source_scan import SourceInvariantViolation, imports, violation


def audit_workflow_family_firewall(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    checks = (
        (root / "noetrium_platform" / "research" / "execution" / "workflow" / "implementations" / "agent_turn", "agent_turn_domain_firewall", (
            "noetrium_platform.capabilities.environment.runtime.api", "noetrium_platform.capabilities.participant.method.api", "noetrium_platform.research.execution.workflow.implementations.context_action",
        )),
        (root / "noetrium_platform" / "research" / "execution" / "workflow" / "implementations" / "context_action", "context_action_domain_firewall", (
            "noetrium_platform.capabilities.participant.agent.api", "noetrium_platform.capabilities.participant.capability.api", "noetrium_platform.research.execution.workflow.implementations.agent_turn",
        )),
    )
    for base, invariant, forbidden in checks:
        if not base.exists():
            continue
        for path in sorted(base.glob("*.py")):
            for module, line in imports(path):
                if any(module.startswith(prefix) for prefix in forbidden):
                    rows.append(violation(root, path, invariant, line, f"workflow family imports unrelated domain authority {module}"))
    return rows


__all__ = ["audit_workflow_family_firewall"]
