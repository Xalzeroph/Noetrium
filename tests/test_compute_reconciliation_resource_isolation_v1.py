from __future__ import annotations

from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.compute.runtime import (
    InMemoryComputeInventory,
    InMemoryComputeScheduler,
)
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


def test_compute_reconciliation_does_not_expire_other_resource_kinds() -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=10.0,
    )
    resources = InMemoryResourceLeaseRegistry(clock=clock)
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
    scheduler = InMemoryComputeScheduler(
        InMemoryComputeInventory(),
        ownership=resources,
        leases=resources,
    )

    clock.advance(2.0)
    assert scheduler.reconcile_expired() == ()

    # Compute reconciliation is kind-scoped. Even though canonical time has
    # crossed the endpoint TTL, this path may not mutate endpoint durable state.
    assert resources._leases["endpoint-lease-a"].state is LeaseState.ACTIVE

    expired = resources.reconcile_expired(
        resource_kind=ResourceKind.NETWORK_ENDPOINT,
    )
    assert tuple(row.lease_id for row in expired) == ("endpoint-lease-a",)
    assert resources._leases["endpoint-lease-a"].state is LeaseState.EXPIRED
