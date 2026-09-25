from __future__ import annotations

from pathlib import Path

from .source_scan import SourceInvariantViolation, imports, violation


_LEGACY_RUNTIME_STATUS_MODULES = ("status_projection.py",)

_LEGACY_OPERATOR_STATUS_MODULES = (
    "runtime_status.py",
    "runtime_status_forensics.py",
    "runtime_status_io.py",
    "runtime_status_model.py",
    "runtime_status_runtime.py",
    "runtime_status_server_session.py",
    "runtime_status_service_state.py",
    "status_service.py",
    "runtime_status_contracts.py",
)

_FORBIDDEN_OPERATOR_STATUS_DOMAINS = (
    "noetrium_platform.infrastructure.lifecycle.launch_control",
    "noetrium_platform.infrastructure.lifecycle.service.runtime",
    "noetrium_platform.infrastructure.lifecycle.session.runtime",
    "noetrium_platform.infrastructure.reliability.forensics",
    "noetrium_platform.infrastructure.reliability.diagnostics.runtime",
)


def audit_status_invariants(root: Path) -> list[SourceInvariantViolation]:
    operator = root / "noetrium_platform" / "product" / "operator"
    rows: list[SourceInvariantViolation] = []

    for name in _LEGACY_OPERATOR_STATUS_MODULES:
        path = operator / name
        if path.exists():
            rows.append(violation(
                root,
                path,
                "status_projection_authority",
                1,
                "operator reintroduced subsystem status projection/composition; project status inside the owning domain and join only shared SubsystemSnapshot contracts",
            ))


    runtime_manager = root / "noetrium_platform" / "research" / "execution" / "runtime" / "manager"
    for name in _LEGACY_RUNTIME_STATUS_MODULES:
        path = runtime_manager / name
        if path.exists():
            rows.append(violation(
                root, path, "status_projection_authority", 1,
                "runtime_manager reintroduced mixed-domain status_projection; keep runtime transaction, recovery lease, and model deployment probes separate",
            ))

    status_runtime = root / "noetrium_platform" / "evidence" / "observability" / "status" / "runtime"
    forbidden_runtime_domains = (
        "noetrium_platform.infrastructure.lifecycle.launch_control",
        "noetrium_platform.infrastructure.lifecycle.service.runtime",
        "noetrium_platform.infrastructure.lifecycle.session.runtime",
        "noetrium_platform.infrastructure.reliability.forensics",
        "noetrium_platform.infrastructure.reliability.diagnostics.runtime",
        "noetrium_platform.product.operator",
        "noetrium_platform.composition",
    )
    for path in sorted(status_runtime.glob("*.py")) if status_runtime.exists() else ():
        for module, line in imports(path):
            if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden_runtime_domains):
                rows.append(violation(
                    root,
                    path,
                    "status_runtime_dependency_firewall",
                    line,
                    f"status runtime imports subsystem/operator implementation {module}; join status_api probes only",
                ))

    return rows


__all__ = ["audit_status_invariants"]
