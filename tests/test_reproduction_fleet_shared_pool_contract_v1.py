from __future__ import annotations

import inspect

from research.reproductions import fleet


def test_repository_fleet_execution_surfaces_shared_pool_dependency() -> None:
    for fn in (
        fleet.preflight_materialized_reproduction_fleet,
        fleet.execute_materialized_reproduction_fleet,
        fleet.preflight_repository_execution_fleet,
        fleet.run_repository_execution_fleet,
    ):
        parameter = inspect.signature(fn).parameters["execution_pool"]
        assert parameter.default is None
