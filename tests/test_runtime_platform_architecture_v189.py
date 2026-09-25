from pathlib import Path

from noetrium_platform.foundation.governance.architecture.runtime_platform_invariants import audit_runtime_platform_invariants


def test_runtime_platform_uses_data_only_authority_bundle() -> None:
    root = Path(__file__).resolve().parents[1]
    assert [row for row in audit_runtime_platform_invariants(root) if row.invariant.startswith("runtime_platform_")] == []
