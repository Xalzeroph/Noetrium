from __future__ import annotations

from pathlib import Path

from .concrete_dependency_invariants import audit_cross_subsystem_concrete_dependencies
from .effect_dependency_invariants import audit_effect_dependency_invariants
from .failure_dependency_invariants import audit_failure_dependency_invariants
from .model_dependency_invariants import audit_model_dependency_invariants
from .observability_dependency_invariants import (
    audit_observability_dependency_invariants,
    audit_observability_logging_leaf_invariants,
)
from .source_scan import SourceInvariantViolation


def audit_dependency_invariants(root: Path) -> list[SourceInvariantViolation]:
    return (
        audit_cross_subsystem_concrete_dependencies(root)
        + audit_effect_dependency_invariants(root)
        + audit_failure_dependency_invariants(root)
        + audit_observability_dependency_invariants(root)
        + audit_observability_logging_leaf_invariants(root)
        + audit_model_dependency_invariants(root)
    )


__all__ = ["audit_dependency_invariants"]
