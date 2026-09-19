from __future__ import annotations

from pathlib import Path

from .source_scan import SourceInvariantViolation, imports, violation


_ORCHESTRATION_PREFIXES = (
    "noetrium_platform.composition",
    "noetrium_platform.capabilities.participant.session.runtime",
    "noetrium_platform.infrastructure.lifecycle.launch_control",
    "noetrium_platform.infrastructure.lifecycle.session.runtime",
    "noetrium_platform.infrastructure.lifecycle.service.runtime",
    "noetrium_platform.research.experimentation",
    "noetrium_platform.research.execution.workflow.implementations",
)

_CONCRETE_PARTICIPANT_PREFIXES = (
    "noetrium_platform.capabilities.participant.definition.runtime",
    "noetrium_platform.capabilities.participant.binding.runtime",
    "noetrium_platform.capabilities.participant.session.runtime",
)


def _python_files(base: Path) -> tuple[Path, ...]:
    return tuple(sorted(base.rglob("*.py"))) if base.exists() else ()


def audit_participant_dependency_invariants(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    api = root / "noetrium_platform" / "capabilities" / "participant" / "core" / "api"
    for path in _python_files(api):
        for module, line in imports(path):
            if any(module.startswith(prefix) for prefix in _CONCRETE_PARTICIPANT_PREFIXES):
                rows.append(violation(root, path, "participant_api_implementation_firewall", line, f"participant API imports concrete participant implementation package {module}"))
            elif any(module.startswith(prefix) for prefix in _ORCHESTRATION_PREFIXES):
                rows.append(violation(root, path, "participant_api_orchestration_firewall", line, f"participant API imports orchestration/runtime package {module}"))

    for prefix in _CONCRETE_PARTICIPANT_PREFIXES:
        implementation = root.joinpath(*prefix.split("."))
        for path in _python_files(implementation):
            for module, line in imports(path):
                if any(module.startswith(orchestration) for orchestration in _ORCHESTRATION_PREFIXES):
                    rows.append(violation(root, path, "participant_implementation_orchestration_firewall", line, f"participant implementation assembly imports orchestration/runtime package {module}"))
    return rows


__all__ = ["audit_participant_dependency_invariants"]
