from __future__ import annotations

from pathlib import Path

from .service_api_invariants import audit_service_api_invariants
from .service_runtime_invariants import audit_service_runtime_invariants
from .service_state_invariants import audit_service_state_invariants
from .service_supervisor_invariants import audit_service_supervisor_invariants
from .source_scan import SourceInvariantViolation


def audit_service_invariants(root: Path) -> list[SourceInvariantViolation]:
    return (
        audit_service_api_invariants(root)
        + audit_service_state_invariants(root)
        + audit_service_runtime_invariants(root)
        + audit_service_supervisor_invariants(root)
    )


__all__ = ["audit_service_invariants"]
