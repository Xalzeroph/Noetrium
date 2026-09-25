from pathlib import Path

from noetrium_platform.foundation.governance.architecture.telemetry_invariants import audit_telemetry_invariants


def test_telemetry_domain_does_not_own_sqlite_or_private_object_graph() -> None:
    root = Path(__file__).resolve().parents[1]
    findings = [
        row for row in audit_telemetry_invariants(root)
        if row.invariant.startswith("telemetry_")
    ]
    assert findings == []
