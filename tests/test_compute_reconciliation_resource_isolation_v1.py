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
)


def test_compute_reconciliation_does_not_expire_other_resource_kinds() -> None:
    resources = InMemoryResourceLeaseRegistry()
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
        now=10.0,
    )
    scheduler = InMemoryComputeScheduler(
        InMemoryComputeInventory(),
        ownership=resources,
        leases=resources,
    )

    assert scheduler.reconcile_expired(now=12.0) == ()

    # Read inside the endpoint lease lifetime. If Compute had globally
    # reconciled leases, durable state would already be EXPIRED.
    assert resources.get("endpoint-lease-a", now=10.5).state is LeaseState.ACTIVE
