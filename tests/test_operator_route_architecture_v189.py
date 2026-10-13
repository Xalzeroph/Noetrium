from pathlib import Path

from noetrium_platform.foundation.governance.architecture.operator_route_invariants import audit_operator_route_invariants


def test_operator_command_families_are_independent_routes() -> None:
    root = Path(__file__).resolve().parents[1]
    assert [row for row in audit_operator_route_invariants(root) if row.invariant == "operator_route_family_boundary"] == []
