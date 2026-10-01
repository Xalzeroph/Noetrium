from __future__ import annotations

from noetrium_platform.infrastructure.resources.lease.runtime import ResourceLeaseRegistry

import sqlite3

from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseState,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceLeaseCardinality,
    ResourceLeaseConflict,
    ResourceOwner,
    ResourceOwnership,
)
from noetrium_platform.infrastructure.resources.lease.runtime import (
    ManualLeaseClock,
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


def test_active_lease_enumeration_is_kind_scoped(tmp_path) -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=10.0,
    )
    database = tmp_path / "resource.sqlite"
    registry = ResourceLeaseRegistry(database, clock=clock)
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


def test_shared_resource_admits_multiple_fenced_consumers(tmp_path) -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=10.0,
    )
    registry = ResourceLeaseRegistry(tmp_path / "shared.sqlite", clock=clock)
    resource = ResourceIdentity(ResourceKind.RUNTIME_FABRIC, "host-runtime-fabric")
    registry.register_owner(
        ResourceOwner(
            resource,
            PLATFORM_SCOPE,
            ResourceOwnership.SHARED,
            ResourceLeaseCardinality.MULTI_ACTIVE,
        )
    )

    first = registry.acquire(
        ResourceLease(
            "fabric-consumer-a",
            resource,
            PLATFORM_SCOPE,
            "runtime-fabric-consumer",
        ),
        ttl_seconds=120.0,
    )
    second = registry.acquire(
        ResourceLease(
            "fabric-consumer-b",
            resource,
            PLATFORM_SCOPE,
            "runtime-fabric-consumer",
        ),
        ttl_seconds=120.0,
    )

    assert first.fencing_token != second.fencing_token
    assert registry.active_for(resource) == (first, second)
    registry.release(first.lease_id, fencing_token=first.fencing_token)
    assert registry.active_for(resource) == (second,)


def test_non_shared_resource_remains_single_active_lease(tmp_path) -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=10.0,
    )
    registry = ResourceLeaseRegistry(tmp_path / "exclusive.sqlite", clock=clock)
    resource = ResourceIdentity(ResourceKind.CONTAINER, "exclusive-container")
    registry.register_owner(ResourceOwner(resource, PLATFORM_SCOPE))
    registry.acquire(
        ResourceLease(
            "exclusive-a",
            resource,
            PLATFORM_SCOPE,
            "container",
        ),
        ttl_seconds=120.0,
    )

    try:
        registry.acquire(
            ResourceLease(
                "exclusive-b",
                resource,
                PLATFORM_SCOPE,
                "container",
            ),
            ttl_seconds=120.0,
        )
    except ResourceLeaseConflict:
        pass
    else:
        raise AssertionError("exclusive resource admitted a second active lease")
