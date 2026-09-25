from __future__ import annotations

from pathlib import Path

from .model_recovery_invariants import audit_model_recovery_observability_boundary
from .model_runtime_api_invariants import audit_runtime_model_api_boundary
from .model_storage_invariants import audit_model_storage_boundaries
from .source_scan import SourceInvariantViolation


def audit_model_invariants(root: Path) -> list[SourceInvariantViolation]:
    return (
        audit_model_storage_boundaries(root)
        + audit_model_recovery_observability_boundary(root)
        + audit_runtime_model_api_boundary(root)
    )


__all__ = ["audit_model_invariants"]
