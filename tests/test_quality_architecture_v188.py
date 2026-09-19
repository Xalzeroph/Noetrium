from pathlib import Path

from noetrium_platform.foundation.governance.architecture.quality_invariants import audit_quality_invariants


def test_no_degradation_scanners_have_single_responsibility() -> None:
    root = Path(__file__).resolve().parents[1]
    assert [row for row in audit_quality_invariants(root) if row.invariant.startswith("no_degradation_")] == []
