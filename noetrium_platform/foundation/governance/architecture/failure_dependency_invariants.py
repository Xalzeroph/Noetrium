from __future__ import annotations

from pathlib import Path

from .source_scan import SourceInvariantViolation, imports, violation


def audit_failure_dependency_invariants(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    protected = (
        root / "projects", root / "noetrium_platform" / "research" / "experimentation" / "experiment", root / "noetrium_platform" / "research" / "execution" / "workflow" / "implementations",
        root / "noetrium_platform" / "research" / "execution" / "runtime" / "manager", root / "noetrium_platform" / "capabilities" / "model" / "serving",
        root / "noetrium_platform" / "infrastructure" / "lifecycle" / "service" / "runtime", root / "noetrium_platform" / "capabilities" / "participant" / "agent" / "api",
        root / "noetrium_platform" / "capabilities" / "participant" / "capability" / "api", root / "noetrium_platform" / "capabilities" / "environment" / "runtime" / "api",
        root / "noetrium_platform" / "capabilities" / "participant" / "method" / "api", root / "noetrium_platform" / "capabilities" / "participant" / "core" / "api",
        root / "noetrium_platform" / "infrastructure" / "reliability" / "effect" / "api", root / "noetrium_platform" / "infrastructure" / "reliability" / "failure" / "api",
    )
    for base in protected:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            for module, line in imports(path):
                if module.startswith("noetrium_platform.infrastructure.reliability.forensics"):
                    rows.append(violation(root, path, "failure_forensics_dependency_direction", line, f"domain/runtime code imports forensic implementation {module}; use noetrium_platform.infrastructure.reliability.failure.api or an injected port"))

    forensics = root / "noetrium_platform" / "infrastructure" / "reliability" / "forensics"
    if forensics.exists():
        for path in sorted(forensics.glob("*.py")):
            if path.name != "__init__.py":
                rows.append(violation(
                    root, path, "forensics_layer_layout", 1,
                    f"forensic implementation module {path.name} is flat at subsystem root; use api/runtime/providers/composition",
                ))
    for legacy_name in ("failure.py", "failure_builder.py", "redaction.py", "service_crash.py"):
        for path in sorted(forensics.rglob(legacy_name)) if forensics.exists() else ():
            rows.append(violation(root, path, "failure_contract_authority", 1, f"forensic backend reintroduced failure semantic/domain adapter in {legacy_name}"))
    forbidden_domain_prefixes = (
        "noetrium_platform.infrastructure.lifecycle.service.runtime", "noetrium_platform.capabilities.participant.method.api", "noetrium_platform.capabilities.environment.runtime.api",
        "noetrium_platform.capabilities.participant.agent.api", "noetrium_platform.capabilities.participant.capability.api", "noetrium_platform.research.execution.workflow.implementations",
        "noetrium_platform.research.experimentation.study", "noetrium_platform.capabilities.model.serving", "noetrium_platform.infrastructure.lifecycle.launch_control", "projects",
    )
    for path in sorted(forensics.rglob("*.py")):
        for module, line in imports(path):
            if module.startswith(forbidden_domain_prefixes):
                rows.append(violation(root, path, "failure_contract_authority", line, f"forensic backend imports domain implementation {module}; domain-to-failure mapping belongs in an integration adapter"))
    return rows


__all__ = ["audit_failure_dependency_invariants"]
