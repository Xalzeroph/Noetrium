from __future__ import annotations

import sqlite3

from tests.resource_compute_support import TestComputeInventory

from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.compute.runtime import (
    ComputeScheduler,
)
from noetrium_platform.infrastructure.resources.lease.api import (
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceOwner,
)
from noetrium_platform.infrastructure.resources.lease.runtime import ManualLeaseClock
from noetrium_platform.infrastructure.resources.providers import SQLiteResourceLeaseRegistry


def test_compute_reconciliation_does_not_expire_other_resource_kinds(tmp_path) -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=10.0,
    )
    database = tmp_path / "resources.sqlite"
    resources = SQLiteResourceLeaseRegistry(database, clock=clock)
    endpoint = ResourceIdentity(ResourceKind.NETWORK_ENDPOINT, "endpoint-a")
    resources.register_owner(ResourceOwner(endpoint, PLATFORM_SCOPE))
    resources.acquire(
        ResourceLease(
            "endpoint-lease-a",
            endpoint,
            PLATFORM_SCOPE,
            "unrelated endpoint",
        ),
        ttl_seconds=1.0,
    )
    scheduler = ComputeScheduler(
        database,
        TestComputeInventory(),
        clock=clock,
    )

    clock.advance(2.0)
    assert scheduler.reconcile_expired() == ()

    # Compute reconciliation is kind-scoped. Even though canonical time has
    # crossed the endpoint TTL, this path may not mutate endpoint durable state.
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT state FROM resource_leases WHERE lease_id=?", ("endpoint-lease-a",)).fetchone()[0] == "active"

    expired = resources.reconcile_expired(
        resource_kind=ResourceKind.NETWORK_ENDPOINT,
    )
    assert tuple(row.lease_id for row in expired) == ("endpoint-lease-a",)
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT state FROM resource_leases WHERE lease_id=?", ("endpoint-lease-a",)).fetchone()[0] == "expired"
