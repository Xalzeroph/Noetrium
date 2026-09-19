from __future__ import annotations

from dataclasses import fields
from time import time

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
from noetrium_platform.infrastructure.resources.lease.runtime import InMemoryResourceLeaseRegistry
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
    registry = InMemoryResourceLeaseRegistry()
    base = time() + 60.0
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
        now=base,
    )
    assert generation_one.fencing_token == 1
    expired = registry.reconcile_expired(now=base + 6.0)
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
        now=base + 6.0,
    )
    assert generation_two.holder_generation == 2
    assert generation_two.fencing_token == 2

    with pytest.raises(ResourceLeaseConflict, match="stale lease fencing token"):
        registry.renew(
            generation_two.lease_id,
            fencing_token=generation_one.fencing_token,
            ttl_seconds=5.0,
            now=base + 7.0,
        )

    stale_release = registry.release(generation_one.lease_id, now=base + 7.0)
    assert stale_release.lease_id == generation_one.lease_id
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
            now=base + 7.0,
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
    base = time() + 60.0

    first = SQLiteResourceLeaseRegistry(database)
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
        now=base,
    )
    assert generation_one.fencing_token == 1
    assert first.reconcile_expired(now=base + 6.0)[0].state is LeaseState.EXPIRED

    restarted = SQLiteResourceLeaseRegistry(database)
    generation_two = restarted.acquire(
        ResourceLease(
            "restart-carrier-g2",
            resource,
            PLATFORM_SCOPE,
            "mutable transport",
            holder_generation=2,
        ),
        ttl_seconds=20.0,
        now=base + 6.0,
    )
    assert generation_two.fencing_token == 2

    after_restart = SQLiteResourceLeaseRegistry(database)
    with pytest.raises(ResourceLeaseConflict, match="stale lease fencing token"):
        after_restart.renew(
            generation_two.lease_id,
            fencing_token=generation_one.fencing_token,
            ttl_seconds=20.0,
            now=base + 7.0,
        )
    assert after_restart.get(generation_two.lease_id).fencing_token == 2
