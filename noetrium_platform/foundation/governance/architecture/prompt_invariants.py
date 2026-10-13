from __future__ import annotations

from pathlib import Path

from .prompt_api_invariants import audit_prompt_api_invariants
from .prompt_publication_invariants import audit_prompt_publication_invariants
from .prompt_trace_invariants import audit_prompt_trace_invariants
from .source_scan import SourceInvariantViolation


def audit_prompt_invariants(root: Path) -> list[SourceInvariantViolation]:
    return (
        audit_prompt_publication_invariants(root)
        + audit_prompt_api_invariants(root)
        + audit_prompt_trace_invariants(root)
    )


__all__ = ["audit_prompt_invariants"]
