from __future__ import annotations

from pathlib import Path

from .source_scan import SourceInvariantViolation, imports, violation


def audit_service_api_invariants(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    api = root / "noetrium_platform" / "infrastructure" / "lifecycle" / "service" / "api"
    forbidden_api = (
        "noetrium_platform.infrastructure.lifecycle.service.runtime",
        "noetrium_platform.infrastructure.lifecycle.launch_control",
        "noetrium_platform.research.experimentation.study",
        "noetrium_platform.composition",
        "noetrium_platform.infrastructure.reliability.forensics",
        "noetrium_platform.product.operator",
    )
    if api.exists():
        for path in sorted(api.rglob("*.py")):
            for module, line in imports(path):
                if module.startswith(forbidden_api):
                    rows.append(violation(
                        root,
                        path,
                        "service_api_dependency_firewall",
                        line,
                        f"service API imports implementation/orchestration layer {module}",
                    ))

    consumers = (
        ("runtime-manager", root / "noetrium_platform" / "research" / "execution" / "runtime" / "manager"),
        ("experiment", root / "noetrium_platform" / "research" / "experimentation" / "experiment"),
        ("workflows", root / "noetrium_platform" / "research" / "execution" / "workflow" / "implementations"),
        ("operator", root / "noetrium_platform" / "product" / "operator"),
    )
    for package_name, package in consumers:
        if not package.exists():
            continue
        for path in sorted(package.rglob("*.py")):
            for module, line in imports(path):
                if module == "noetrium_platform.infrastructure.lifecycle.service.runtime" or module.startswith("noetrium_platform.infrastructure.lifecycle.service.runtime."):
                    rows.append(violation(root, path, "service_external_api_boundary", line, f"{package_name} imports service implementation {module}; depend on noetrium_platform.infrastructure.lifecycle.service.api"))

    legacy = root / "noetrium_platform" / "infrastructure" / "lifecycle" / "service" / "runtime" / "runtime_ports.py"
    if legacy.exists():
        rows.append(violation(
            root,
            legacy,
            "service_external_api_boundary",
            1,
            "Service runtime cross-system ABI must live in runtime.service.api, not runtime.runtime_ports",
        ))
    return rows


__all__ = ["audit_service_api_invariants"]
