from __future__ import annotations

from pathlib import Path

from .operator_route_invariants import audit_operator_route_invariants
from .source_scan import SourceInvariantViolation, imports, violation


def _audit_diagnostics_api_firewall(root: Path) -> list[SourceInvariantViolation]:
    api = root / "noetrium_platform" / "infrastructure" / "reliability" / "diagnostics" / "api"
    if not api.exists():
        return []
    forbidden = (
        "noetrium_platform.infrastructure.reliability.forensics",
        "noetrium_platform.product.operator",
        "noetrium_platform.evidence.observability.telemetry",
        "noetrium_platform.infrastructure.reliability.diagnostics.runtime",
    )
    rows: list[SourceInvariantViolation] = []
    for path in sorted(api.rglob("*.py")):
        for module, line in imports(path):
            if module.startswith(forbidden):
                rows.append(violation(
                    root,
                    path,
                    "diagnostics_api_backend_firewall",
                    line,
                    f"diagnostics API imports implementation/presentation module {module}",
                ))
    return rows


def _audit_diagnostics_service_direction(root: Path) -> list[SourceInvariantViolation]:
    diagnostics = root / "noetrium_platform" / "infrastructure" / "reliability" / "diagnostics" / "runtime"
    if not diagnostics.exists():
        return []
    forbidden = (
        "noetrium_platform.infrastructure.reliability.forensics",
        "noetrium_platform.product.operator",
        "noetrium_platform.evidence.observability.telemetry",
    )
    rows: list[SourceInvariantViolation] = []
    for path in sorted(diagnostics.rglob("*.py")):
        for module, line in imports(path):
            if module.startswith(forbidden):
                rows.append(violation(
                    root,
                    path,
                    "diagnostics_service_dependency_direction",
                    line,
                    f"diagnostic algorithm imports concrete backend/UI {module}; depend on diagnostics_api port",
                ))
    return rows


def _audit_diagnostic_authority_locations(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    operator = root / "noetrium_platform" / "product" / "operator"
    for legacy in (
        "diagnosis.py",
        "debug_snapshot.py",
        "triage_plan.py",
        "verify.py",
        "telemetry_reader.py",
        "incident.py",
    ):
        path = operator / legacy
        if path.exists():
            rows.append(violation(
                root,
                path,
                "diagnostics_authority_location",
                1,
                f"diagnostic/query algorithm reintroduced in operator presentation layer: {legacy}",
            ))

    forensics = root / "noetrium_platform" / "infrastructure" / "reliability" / "forensics"
    for legacy in (
        "causal.py",
        "graph_builder.py",
        "graph_projection.py",
        "fingerprint.py",
        "incident_contracts.py",
    ):
        for path in sorted(forensics.rglob(legacy)) if forensics.exists() else ():
            rows.append(violation(
                root,
                path,
                "diagnostics_authority_location",
                1,
                f"diagnostic/failure semantics reintroduced in forensic storage backend: {legacy}",
            ))
    return rows



def _audit_operator_backend_direction(root: Path) -> list[SourceInvariantViolation]:
    operator = root / "noetrium_platform" / "product" / "operator"
    if not operator.exists():
        return []
    forbidden = (
        "noetrium_platform.infrastructure.reliability.forensics",
        "noetrium_platform.evidence.observability.telemetry",
        "noetrium_platform.capabilities.model.serving",
        "noetrium_platform.foundation.governance.release.runtime",
    )
    rows: list[SourceInvariantViolation] = []
    for path in sorted(operator.rglob("*.py")):
        for module, line in imports(path):
            if module.startswith(forbidden):
                rows.append(violation(
                    root, path, "operator_diagnostic_backend_firewall", line,
                    f"operator presentation imports concrete domain/backend implementation {module}; use API/composition ports",
                ))
    return rows

def audit_diagnostics_invariants(root: Path) -> list[SourceInvariantViolation]:
    return (
        _audit_diagnostics_api_firewall(root)
        + _audit_diagnostics_service_direction(root)
        + _audit_diagnostic_authority_locations(root)
        + _audit_operator_backend_direction(root)
        + audit_operator_route_invariants(root)
    )


__all__ = ["audit_diagnostics_invariants"]
