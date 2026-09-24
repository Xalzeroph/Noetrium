from __future__ import annotations

from pathlib import Path

from .source_scan import SourceInvariantViolation, violation


def audit_retired_experiment_orchestration(
    root: Path,
) -> list[SourceInvariantViolation]:
    """Reject reintroduction of retired parallel Experiment execution namespaces."""

    rows: list[SourceInvariantViolation] = []
    retired_roots = (
        root / "noetrium_platform" / "research" / "experimentation" / "experiment",
        (
            root
            / "noetrium_platform"
            / "research"
            / "experimentation"
            / "lifecycle"
            / "experiment"
            / "runtime"
        ),
    )
    for retired in retired_roots:
        if not retired.exists():
            continue
        for path in sorted(retired.rglob("*.py")):
            rows.append(
                violation(
                    root,
                    path,
                    "retired_experiment_orchestration_path",
                    1,
                    "retired parallel Experiment orchestration namespace "
                    "reappeared; execution must enter through Research OS",
                )
            )
    return rows


__all__ = ["audit_retired_experiment_orchestration"]
