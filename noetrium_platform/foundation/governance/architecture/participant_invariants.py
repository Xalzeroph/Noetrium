from __future__ import annotations

from pathlib import Path

from .participant_binding_invariants import audit_participant_binding_invariants
from .participant_dependency_invariants import audit_participant_dependency_invariants
from .participant_lifecycle_invariants import audit_participant_lifecycle_invariants
from .source_scan import SourceInvariantViolation


def audit_participant_invariants(root: Path) -> list[SourceInvariantViolation]:
    return (
        audit_participant_dependency_invariants(root)
        + audit_participant_binding_invariants(root)
        + audit_participant_lifecycle_invariants(root)
    )


__all__ = ["audit_participant_invariants"]
