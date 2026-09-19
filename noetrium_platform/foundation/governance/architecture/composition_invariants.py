from __future__ import annotations

from pathlib import Path

from .composition_family_invariants import audit_composition_family_firewall
from .capability_composition_invariants import audit_capability_composition_boundaries
from .composition_participant_invariants import audit_generic_participant_signatures
from .composition_root_invariants import audit_composition_root_imports
from .composition_workflow_invariants import audit_workflow_family_firewall
from .source_scan import SourceInvariantViolation


def audit_composition_invariants(root: Path) -> list[SourceInvariantViolation]:
    return (
        audit_generic_participant_signatures(root)
        + audit_workflow_family_firewall(root)
        + audit_composition_family_firewall(root)
        + audit_composition_root_imports(root)
        + audit_capability_composition_boundaries(root)
    )


__all__ = ["audit_composition_invariants"]
