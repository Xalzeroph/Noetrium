from __future__ import annotations

from research.reproductions import fleet


def test_reproduction_inventory_has_no_execution_surface() -> None:
    forbidden = (
        "preflight_materialized_reproduction_fleet",
        "execute_materialized_reproduction_fleet",
        "preflight_repository_execution_fleet",
        "run_repository_execution_fleet",
        "ReproductionFleetExecutionResult",
    )
    assert all(not hasattr(fleet, name) for name in forbidden)
