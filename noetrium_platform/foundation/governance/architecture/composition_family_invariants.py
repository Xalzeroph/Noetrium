from __future__ import annotations

from pathlib import Path

from .source_scan import SourceInvariantViolation, imports, violation


def audit_composition_family_firewall(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    composition = root / "noetrium_platform" / "composition"
    retired_paths = (
        composition / "context_action.py",
        composition / "workflows" / "context_action",
    )
    for path in retired_paths:
        if path.exists():
            rows.append(
                violation(
                    root,
                    path,
                    "retired_context_action_path",
                    1,
                    "retired context_action composition path must not return",
                )
            )
    checks = (
        (
            composition / "agent_turn.py",
            "composition_agent_turn_firewall",
            (),
        ),
    )
    for path, invariant, forbidden in checks:
        if not path.exists():
            continue
        for module, line in imports(path):
            if any(module.startswith(prefix) for prefix in forbidden):
                rows.append(violation(root, path, invariant, line, f"composition family imports unrelated domain authority {module}"))

    retired_participant_bridges = (
        composition / "participants" / "agent.py",
        composition / "participants" / "capability.py",
        composition / "participants" / "environment.py",
        composition / "participants" / "method.py",
        composition / "participants" / "generic.py",
    )
    for path in retired_participant_bridges:
        if path.exists():
            rows.append(
                violation(
                    root,
                    path,
                    "retired_participant_bridge",
                    1,
                    "participant bridge split modules are retired; use participants/runtime.py",
                )
            )

    participant_runtime = composition / "participants" / "runtime.py"
    if not participant_runtime.exists():
        rows.append(
            violation(
                root,
                participant_runtime,
                "participant_runtime_missing",
                1,
                "unified participant runtime bridge is required",
            )
        )
    return rows


__all__ = ["audit_composition_family_firewall"]
