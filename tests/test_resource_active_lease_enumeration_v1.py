from __future__ import annotations

import sqlite3

from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseState,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceOwner,
)
from noetrium_platform.infrastructure.resources.lease.runtime import (
    InMemoryResourceLeaseRegistry,
    ManualLeaseClock,
)
from noetrium_platform.infrastructure.resources.providers import (
    SQLiteResourceLeaseRegistry,
)


def _populate(registry) -> tuple[ResourceLease, ResourceLease]:
    container = ResourceIdentity(ResourceKind.CONTAINER, "container-a")
    endpoint = ResourceIdentity(ResourceKind.NETWORK_ENDPOINT, "endpoint-a")
    for resource in (container, endpoint):
        registry.register_owner(ResourceOwner(resource, PLATFORM_SCOPE))
    container_lease = registry.acquire(
        ResourceLease(
            "lease-container-a",
            container,
            PLATFORM_SCOPE,
            "container",
        ),
        ttl_seconds=100.0,
    )
    endpoint_lease = registry.acquire(
        ResourceLease(
            "lease-endpoint-a",
            endpoint,
            PLATFORM_SCOPE,
            "endpoint",
        ),
        ttl_seconds=1.0,
    )
    return container_lease, endpoint_lease


def test_in_memory_active_lease_enumeration_is_kind_scoped() -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=10.0,
    )
    registry = InMemoryResourceLeaseRegistry(clock=clock)
    container_lease, endpoint_lease = _populate(registry)

    clock.advance(2.0)
    rows = registry.active_leases(resource_kind=ResourceKind.CONTAINER)

    assert rows == (container_lease,)
    assert registry._leases[endpoint_lease.lease_id].state is LeaseState.ACTIVE

    assert registry.active_leases(
        resource_kind=ResourceKind.NETWORK_ENDPOINT
    ) == ()
    assert registry._leases[endpoint_lease.lease_id].state is LeaseState.EXPIRED


def test_sqlite_active_lease_enumeration_is_kind_scoped(tmp_path) -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=10.0,
    )
    database = tmp_path / "resource.sqlite"
    registry = SQLiteResourceLeaseRegistry(database, clock=clock)
    container_lease, endpoint_lease = _populate(registry)

    clock.advance(2.0)
    rows = registry.active_leases(resource_kind=ResourceKind.CONTAINER)

    assert rows == (container_lease,)
    with sqlite3.connect(database) as conn:
        state = conn.execute(
            "SELECT state FROM resource_leases WHERE lease_id=?",
            (endpoint_lease.lease_id,),
        ).fetchone()
    assert state == (LeaseState.ACTIVE.value,)

    assert registry.active_leases(
        resource_kind=ResourceKind.NETWORK_ENDPOINT
    ) == ()
    with sqlite3.connect(database) as conn:
        state = conn.execute(
            "SELECT state FROM resource_leases WHERE lease_id=?",
            (endpoint_lease.lease_id,),
        ).fetchone()
    assert state == (LeaseState.EXPIRED.value,)
