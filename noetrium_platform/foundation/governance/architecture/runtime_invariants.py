from __future__ import annotations

from pathlib import Path

from .runtime_control_invariants import audit_runtime_control_invariants
from .runtime_heartbeat_invariants import audit_runtime_heartbeat_invariants
from .runtime_observability_invariants import audit_runtime_observability_invariants
from .runtime_platform_invariants import audit_runtime_platform_invariants
from .runtime_recovery_invariants import audit_runtime_recovery_invariants
from .runtime_service_start_invariants import audit_runtime_service_start_invariants
from .runtime_state_invariants import audit_runtime_state_invariants
from .source_scan import SourceInvariantViolation


def audit_runtime_invariants(root: Path) -> list[SourceInvariantViolation]:
    return (
        audit_runtime_control_invariants(root)
        + audit_runtime_recovery_invariants(root)
        + audit_runtime_service_start_invariants(root)
        + audit_runtime_state_invariants(root)
        + audit_runtime_heartbeat_invariants(root)
        + audit_runtime_observability_invariants(root)
        + audit_runtime_platform_invariants(root)
    )


__all__ = ["audit_runtime_invariants"]
