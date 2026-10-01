from __future__ import annotations

from noetrium_platform.infrastructure.resources.lease.runtime import ResourceLeaseRegistry

from tests.resource_lease_support import TestResourceLeaseRegistry

from pathlib import Path

import pytest

from noetrium_platform.composition.reliability_resources import RecoveryLeaseAdapter
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseState,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceLeaseClockConflict,
    ResourceOwner,
)
from noetrium_platform.infrastructure.resources.lease.runtime import (
    ManualLeaseClock,
)
from noetrium_platform.infrastructure.reliability.recovery.api.lease import (
    RecoveryLeaseBusy,
)


def _registry(kind: str, tmp_path: Path, clock: ManualLeaseClock):
    if kind == "memory":
        return TestResourceLeaseRegistry(clock=clock)
    return ResourceLeaseRegistry(
        tmp_path / "lease-clock.sqlite3",
        clock=clock,
    )


@pytest.mark.parametrize("kind", ("memory", "sqlite"))
def test_wall_clock_jumps_cannot_expire_or_extend_lease_authority(
    tmp_path: Path,
    kind: str,
) -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=100.0,
        wall_epoch_seconds=10_000.0,
    )
    registry = _registry(kind, tmp_path, clock)
    resource = ResourceIdentity(ResourceKind.STORAGE, "clock-jump")
    registry.register_owner(ResourceOwner(resource, PLATFORM_SCOPE))
    granted = registry.acquire(
        ResourceLease(
            "lease-clock-jump",
            resource,
            PLATFORM_SCOPE,
            "clock anomaly proof",
        ),
        ttl_seconds=10.0,
    )
    assert granted.expires_at_epoch_s == pytest.approx(10_010.0)

    clock.jump_wall(-5_000.0)
    assert registry.get(granted.lease_id).state is LeaseState.ACTIVE

    clock.jump_wall(2_000_000.0)
    assert registry.get(granted.lease_id).state is LeaseState.ACTIVE

    clock.advance(9.0, wall_seconds=0.0)
    assert registry.get(granted.lease_id).state is LeaseState.ACTIVE

    clock.advance(2.0, wall_seconds=0.0)
    assert registry.get(granted.lease_id).state is LeaseState.EXPIRED


@pytest.mark.parametrize("kind", ("memory", "sqlite"))
def test_suspend_aware_elapsed_time_expires_lease_without_wall_progress(
    tmp_path: Path,
    kind: str,
) -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=50.0,
        wall_epoch_seconds=20_000.0,
    )
    registry = _registry(kind, tmp_path, clock)
    resource = ResourceIdentity(ResourceKind.COMPUTE, "suspend")
    registry.register_owner(ResourceOwner(resource, PLATFORM_SCOPE))
    granted = registry.acquire(
        ResourceLease(
            "lease-suspend",
            resource,
            PLATFORM_SCOPE,
            "suspend proof",
        ),
        ttl_seconds=5.0,
    )

    clock.advance(6.0, wall_seconds=0.0)

    assert registry.get(granted.lease_id).state is LeaseState.EXPIRED


@pytest.mark.parametrize("kind", ("memory", "sqlite"))
def test_same_host_reboot_revokes_old_boot_generation_immediately(
    tmp_path: Path,
    kind: str,
) -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=500.0,
        wall_epoch_seconds=30_000.0,
        host_seed="host-a",
        boot_seed="boot-a",
    )
    registry = _registry(kind, tmp_path, clock)
    resource = ResourceIdentity(ResourceKind.NETWORK_ENDPOINT, "reboot")
    registry.register_owner(ResourceOwner(resource, PLATFORM_SCOPE))
    granted = registry.acquire(
        ResourceLease(
            "lease-reboot",
            resource,
            PLATFORM_SCOPE,
            "reboot proof",
        ),
        ttl_seconds=3_600.0,
    )

    clock.reboot(boot_seed="boot-b", elapsed_seconds=1.0)

    assert registry.get(granted.lease_id).state is LeaseState.EXPIRED
    replacement = registry.acquire(
        ResourceLease(
            granted.lease_id,
            resource,
            PLATFORM_SCOPE,
            "reboot proof",
        ),
        ttl_seconds=30.0,
    )
    assert replacement.fencing_token > granted.fencing_token
    assert replacement.holder_generation > granted.holder_generation


@pytest.mark.parametrize("kind", ("memory", "sqlite"))
def test_different_host_cannot_implicitly_take_over_clock_authority(
    tmp_path: Path,
    kind: str,
) -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=10.0,
        wall_epoch_seconds=40_000.0,
        host_seed="host-a",
        boot_seed="boot-a",
    )
    registry = _registry(kind, tmp_path, clock)
    resource = ResourceIdentity(ResourceKind.CONTAINER, "cross-host")
    registry.register_owner(ResourceOwner(resource, PLATFORM_SCOPE))
    granted = registry.acquire(
        ResourceLease(
            "lease-cross-host",
            resource,
            PLATFORM_SCOPE,
            "cross-host proof",
        ),
        ttl_seconds=5.0,
    )

    clock.move_host(host_seed="host-b")
    with pytest.raises(
        ResourceLeaseClockConflict,
        match="different host clock domain",
    ):
        registry.get(granted.lease_id)

    clock.move_host(host_seed="host-a")
    assert registry.get(granted.lease_id).state is LeaseState.ACTIVE


@pytest.mark.parametrize("kind", ("memory", "sqlite"))
def test_wall_clock_backward_jump_does_not_block_exact_release(
    tmp_path: Path,
    kind: str,
) -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=20.0,
        wall_epoch_seconds=50_000.0,
    )
    registry = _registry(kind, tmp_path, clock)
    resource = ResourceIdentity(ResourceKind.WORKSPACE, "release")
    registry.register_owner(ResourceOwner(resource, PLATFORM_SCOPE))
    granted = registry.acquire(
        ResourceLease(
            "lease-release",
            resource,
            PLATFORM_SCOPE,
            "release proof",
        ),
        ttl_seconds=30.0,
    )
    clock.jump_wall(-10_000.0)
    clock.advance(1.0, wall_seconds=0.0)

    released = registry.release(
        granted.lease_id,
        fencing_token=granted.fencing_token,
    )

    assert released.state is LeaseState.RELEASED


@pytest.mark.parametrize("kind", ("memory", "sqlite"))
def test_caller_supplied_wall_time_cannot_force_lease_expiry(
    tmp_path: Path,
    kind: str,
) -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=10.0,
        wall_epoch_seconds=55_000.0,
    )
    registry = _registry(kind, tmp_path, clock)
    resource = ResourceIdentity(ResourceKind.CONTAINER, "caller-now")
    registry.register_owner(ResourceOwner(resource, PLATFORM_SCOPE))
    granted = registry.acquire(
        ResourceLease(
            "lease-caller-now",
            resource,
            PLATFORM_SCOPE,
            "caller now must not be authority",
        ),
        ttl_seconds=10.0,
        now=1.0,
    )

    assert granted.expires_at_epoch_s == pytest.approx(55_010.0)
    assert registry.reconcile_expired(now=10**12) == ()
    assert registry.get(granted.lease_id, now=10**12).state is LeaseState.ACTIVE

    clock.advance(11.0, wall_seconds=0.0)
    assert registry.get(granted.lease_id, now=1.0).state is LeaseState.EXPIRED


@pytest.mark.parametrize("kind", ("memory", "sqlite"))
def test_recovery_authority_ignores_wall_clock_jumps(
    tmp_path: Path,
    kind: str,
) -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=100.0,
        wall_epoch_seconds=60_000.0,
    )
    registry = _registry(kind, tmp_path, clock)
    recovery = RecoveryLeaseAdapter(registry, registry)

    acquired = recovery.acquire(
        "runtime-owner",
        "manifest-a",
        ttl_seconds=10.0,
    )

    clock.jump_wall(5_000_000.0)
    assert recovery.assert_owned("runtime-owner", "manifest-a") == acquired

    clock.jump_wall(-10_000_000.0)
    clock.advance(9.0, wall_seconds=0.0)
    assert recovery.assert_owned("runtime-owner", "manifest-a").owner_id == (
        "runtime-owner"
    )

    clock.advance(2.0, wall_seconds=0.0)
    with pytest.raises(RecoveryLeaseBusy, match="not held"):
        recovery.assert_owned("runtime-owner", "manifest-a")


@pytest.mark.parametrize("kind", ("memory", "sqlite"))
def test_recovery_authority_reboot_fences_old_generation(
    tmp_path: Path,
    kind: str,
) -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=100.0,
        wall_epoch_seconds=70_000.0,
        boot_seed="boot-a",
    )
    registry = _registry(kind, tmp_path, clock)
    recovery = RecoveryLeaseAdapter(registry, registry)

    recovery.acquire(
        "runtime-owner-a",
        "manifest-a",
        ttl_seconds=3_600.0,
    )
    clock.reboot(boot_seed="boot-b", elapsed_seconds=1.0)

    with pytest.raises(RecoveryLeaseBusy, match="not held"):
        recovery.assert_owned("runtime-owner-a", "manifest-a")

    replacement = recovery.acquire(
        "runtime-owner-b",
        "manifest-b",
        ttl_seconds=30.0,
    )
    assert replacement.owner_id == "runtime-owner-b"
    assert replacement.manifest_digest == "manifest-b"
