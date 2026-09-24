from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.governance.architecture.observability_dependency_invariants import (
    audit_observability_logging_leaf_invariants,
)


def test_platform_has_no_stdlib_logging_bypass() -> None:
    root = Path(__file__).resolve().parents[1]
    violations = audit_observability_logging_leaf_invariants(root)
    assert not [
        row for row in violations
        if row.invariant == "logging_stdlib_bypass"
    ]


def test_stdlib_logging_bypass_is_rejected(tmp_path: Path) -> None:
    logging_root = (
        tmp_path
        / "noetrium_platform"
        / "evidence"
        / "observability"
        / "logging"
    )
    logging_root.mkdir(parents=True)
    offender = tmp_path / "noetrium_platform" / "rogue.py"
    offender.write_text(
        "import logging\n\ndef emit():\n    return logging.getLogger(__name__)\n",
        encoding="utf-8",
    )

    violations = audit_observability_logging_leaf_invariants(tmp_path)

    matches = [
        row for row in violations
        if row.invariant == "logging_stdlib_bypass"
    ]
    assert len(matches) == 1
    assert matches[0].path == "noetrium_platform/rogue.py"
