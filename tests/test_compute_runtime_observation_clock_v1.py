from __future__ import annotations

import pytest

from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeHost,
    ComputePlacementUnavailable,
    ComputeRequirement,
    HostRuntimeSnapshot,
    HostRuntimeStatus,
)
from noetrium_platform.infrastructure.resources.compute.runtime import (
    InMemoryComputeInventory,
    SQLiteComputeScheduler,
)
from noetrium_platform.infrastructure.resources.lease.runtime import ManualLeaseClock


class _FixedHostObserver:
    def snapshot(self) -> HostRuntimeSnapshot:
        return HostRuntimeSnapshot(
            True,
            (
                HostRuntimeStatus(
                    "host-a",
                    True,
                    effective_cpu_cores=8.0,
                    cpu_load_1m=0.0,
                    available_memory_bytes=32,
                ),
            ),
            observed_at_epoch_s=100.0,
        )


def test_durable_runtime_freshness_uses_lease_time_authority(tmp_path) -> None:
    scope = ScopeIdentity(ScopeKind.PROJECT, "freshness-clock")
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("host-a", scope, 8, 32))
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.5,
    )
    scheduler = SQLiteComputeScheduler(
        tmp_path / "compute.sqlite3",
        inventory,
        clock=clock,
        host_runtime_observer=_FixedHostObserver(),
    )
    requirement = ComputeRequirement(
        cpu_cores=1,
        memory_bytes=1,
        max_runtime_observation_age_seconds=1.0,
    )

    fresh = scheduler.allocate("fresh", scope, requirement)
    assert fresh.host_id == "host-a"

    clock.advance(2.0)

    with pytest.raises(ComputePlacementUnavailable):
        scheduler.allocate("stale", scope, requirement)
