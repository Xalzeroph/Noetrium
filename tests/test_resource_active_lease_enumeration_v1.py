from __future__ import annotations

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
)
from noetrium_platform.infrastructure.resources.providers import (
    SQLiteResourceLeaseRegistry,
)


def _exercise(registry) -> None:
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
        now=10.0,
    )
    endpoint_lease = registry.acquire(
        ResourceLease(
            "lease-endpoint-a",
            endpoint,
            PLATFORM_SCOPE,
            "endpoint",
        ),
        ttl_seconds=1.0,
        now=10.0,
    )

    rows = registry.active_leases(
        resource_kind=ResourceKind.CONTAINER,
        now=12.0,
    )

    assert rows == (container_lease,)
    # A scoped CONTAINER enumeration must not mutate an unrelated expired
    # endpoint lease as a side effect.
    assert registry.get(endpoint_lease.lease_id, now=10.5).state is LeaseState.ACTIVE


def test_in_memory_active_lease_enumeration_is_kind_scoped() -> None:
    _exercise(InMemoryResourceLeaseRegistry())


def test_sqlite_active_lease_enumeration_is_kind_scoped(tmp_path) -> None:
    _exercise(SQLiteResourceLeaseRegistry(tmp_path / "resource.sqlite"))
