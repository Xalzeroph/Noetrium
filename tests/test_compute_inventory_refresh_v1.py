from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeHost,
    ComputeHostSchedulingState,
    ComputeInventoryConflict,
)
from noetrium_platform.infrastructure.resources.compute.runtime import (
    InMemoryComputeInventory,
    SQLiteComputeInventory,
)


def _scope() -> ScopeIdentity:
    return ScopeIdentity(ScopeKind.PROJECT, "inventory-refresh")


def _host() -> ComputeHost:
    return ComputeHost("node-a", _scope(), 8, 1024)


def test_in_memory_inventory_refresh_is_exact_generation_cas() -> None:
    inventory = InMemoryComputeInventory()
    initial = _host()
    draining = replace(
        initial,
        scheduling_state=ComputeHostSchedulingState.DRAINING,
    )
    active_again = replace(
        draining,
        scheduling_state=ComputeHostSchedulingState.ACTIVE,
    )

    inventory.register_host(initial)
    assert inventory.replace_host(initial, draining) == draining

    with pytest.raises(ComputeInventoryConflict, match="stale"):
        inventory.replace_host(initial, active_again)

    assert inventory.replace_host(draining, active_again) == active_again
    assert inventory.host(initial.host_id) == active_again


def test_sqlite_inventory_refresh_survives_restart_and_fences_stale_observer(
    tmp_path,
) -> None:
    path = tmp_path / "compute-inventory.sqlite3"
    inventory = SQLiteComputeInventory(path)
    initial = _host()
    draining = replace(
        initial,
        scheduling_state=ComputeHostSchedulingState.DRAINING,
    )
    active_again = replace(
        draining,
        scheduling_state=ComputeHostSchedulingState.ACTIVE,
    )

    inventory.register_host(initial)
    assert inventory.replace_host(initial, draining) == draining

    restarted = SQLiteComputeInventory(path)
    assert restarted.host(initial.host_id) == draining

    with pytest.raises(ComputeInventoryConflict, match="stale"):
        restarted.replace_host(initial, active_again)

    assert restarted.replace_host(draining, active_again) == active_again
