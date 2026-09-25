from __future__ import annotations

from dataclasses import fields
import pytest

from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseState,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceLeaseConflict,
    ResourceOwner,
    ResourceOwnership,
)
from noetrium_platform.infrastructure.resources.lease.runtime import (
    InMemoryResourceLeaseRegistry,
    ManualLeaseClock,
)
from noetrium_platform.infrastructure.resources.providers import SQLiteResourceLeaseRegistry
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE


@pytest.mark.parametrize(
    ("kind", "resource_id"),
    (
        (ResourceKind.STORAGE, "carrier:file:large-result.bin"),
        (ResourceKind.CACHE, "carrier:shared-memory:segment-a"),
        (ResourceKind.NETWORK_ENDPOINT, "carrier:socket:127.0.0.1:41000"),
    ),
)
def test_shared_mutable_carrier_reuse_is_generation_fenced(
    kind: ResourceKind,
    resource_id: str,
) -> None:
    clock = ManualLeaseClock(elapsed_seconds=1.0, wall_epoch_seconds=100.0)
    registry = InMemoryResourceLeaseRegistry(clock=clock)
    resource = ResourceIdentity(kind, resource_id)
    registry.register_owner(
        ResourceOwner(resource, PLATFORM_SCOPE, ResourceOwnership.SHARED)
    )
    generation_one = registry.acquire(
        ResourceLease(
            "carrier-lease-g1",
            resource,
            PLATFORM_SCOPE,
            "mutable large-value transport",
            holder_generation=1,
        ),
        ttl_seconds=5.0,
    )
    assert generation_one.fencing_token == 1
    clock.advance(6.0)
    expired = registry.reconcile_expired()
    assert len(expired) == 1
    assert expired[0].lease_id == generation_one.lease_id
    assert expired[0].state is LeaseState.EXPIRED

    generation_two = registry.acquire(
        ResourceLease(
            "carrier-lease-g2",
            resource,
            PLATFORM_SCOPE,
            "mutable large-value transport",
            holder_generation=2,
        ),
        ttl_seconds=5.0,
    )
    assert generation_two.holder_generation == 2
    assert generation_two.fencing_token == 2

    with pytest.raises(ResourceLeaseConflict, match="stale lease fencing token"):
        registry.renew(
            generation_two.lease_id,
            fencing_token=generation_one.fencing_token,
            ttl_seconds=5.0,
        )

    with pytest.raises(Exception):
        registry.release(
            generation_one.lease_id,
            fencing_token=generation_one.fencing_token,
        )
    assert registry.active_for(resource) == (generation_two,)

    with pytest.raises(ResourceLeaseConflict, match="resource already has an active lease"):
        registry.acquire(
            ResourceLease(
                "carrier-lease-stale-g1",
                resource,
                PLATFORM_SCOPE,
                "stale generation reuse",
                holder_generation=1,
            ),
            ttl_seconds=5.0,
        )


def test_resource_lease_cannot_masquerade_as_durable_content_evidence() -> None:
    names = {field.name for field in fields(ResourceLease)}
    assert {"resource", "holder_generation", "fencing_token"} <= names
    assert not names & {
        "content_digest",
        "artifact_digest",
        "evidence_ref",
        "evidence_refs",
        "payload",
    }


def test_shared_carrier_fence_persists_across_sqlite_restart(tmp_path) -> None:
    database = tmp_path / "resource-leases.sqlite"
    resource = ResourceIdentity(ResourceKind.STORAGE, "carrier:file:restart.bin")
    clock = ManualLeaseClock(elapsed_seconds=1.0, wall_epoch_seconds=100.0)

    first = SQLiteResourceLeaseRegistry(database, clock=clock)
    first.register_owner(
        ResourceOwner(resource, PLATFORM_SCOPE, ResourceOwnership.SHARED)
    )
    generation_one = first.acquire(
        ResourceLease(
            "restart-carrier-g1",
            resource,
            PLATFORM_SCOPE,
            "mutable transport",
            holder_generation=1,
        ),
        ttl_seconds=5.0,
    )
    assert generation_one.fencing_token == 1
    clock.advance(6.0)
    assert first.reconcile_expired()[0].state is LeaseState.EXPIRED

    restarted = SQLiteResourceLeaseRegistry(database, clock=clock)
    generation_two = restarted.acquire(
        ResourceLease(
            "restart-carrier-g2",
            resource,
            PLATFORM_SCOPE,
            "mutable transport",
            holder_generation=2,
        ),
        ttl_seconds=20.0,
    )
    assert generation_two.fencing_token == 2

    after_restart = SQLiteResourceLeaseRegistry(database, clock=clock)
    with pytest.raises(ResourceLeaseConflict, match="stale lease fencing token"):
        after_restart.renew(
            generation_two.lease_id,
            fencing_token=generation_one.fencing_token,
            ttl_seconds=20.0,
        )
    assert after_restart.get(generation_two.lease_id).fencing_token == 2


@pytest.mark.parametrize("registry_factory", [InMemoryResourceLeaseRegistry, SQLiteResourceLeaseRegistry])
def test_reused_lease_id_rejects_delayed_release_from_old_generation(
    registry_factory,
    tmp_path,
) -> None:
    clock = ManualLeaseClock(elapsed_seconds=1.0, wall_epoch_seconds=100.0)
    registry = (
        registry_factory(clock=clock)
        if registry_factory is InMemoryResourceLeaseRegistry
        else registry_factory(tmp_path / "reused-release.sqlite", clock=clock)
    )
    resource = ResourceIdentity(ResourceKind.CONTAINER, "same-logical-container")
    registry.register_owner(ResourceOwner(resource, PLATFORM_SCOPE))
    requested = ResourceLease(
        "container:same-logical-container",
        resource,
        PLATFORM_SCOPE,
        "managed container",
    )
    old = registry.acquire(requested, ttl_seconds=1.0)
    clock.advance(2.0)
    registry.reconcile_expired()
    current = registry.acquire(requested, ttl_seconds=30.0)

    assert current.fencing_token > old.fencing_token
    with pytest.raises(ResourceLeaseConflict, match="stale lease fencing token"):
        registry.release(
            old.lease_id,
            fencing_token=old.fencing_token,
        )

    active = registry.active_for(resource)
    assert active == (current,)
