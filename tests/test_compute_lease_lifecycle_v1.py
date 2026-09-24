import pytest

from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeHost,
    ComputeRequirement,
)
from noetrium_platform.infrastructure.resources.compute.runtime import (
    ComputePhysicalConvergencePending,
    InMemoryComputeInventory,
    SQLiteComputeScheduler,
)
from noetrium_platform.infrastructure.resources.lease.runtime import (
    InMemoryResourceLeaseRegistry,
    ManualLeaseClock,
)
from tests.resource_compute_support import in_memory_compute_scheduler


def _scope():
    return ScopeIdentity(ScopeKind.PROJECT, "lease-project")


def _inventory(cpu=8):
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("lease-node", _scope(), cpu, 1024))
    return inventory


def _req(cpu=4):
    return ComputeRequirement(cpu_cores=cpu, memory_bytes=128)


def _memory_scheduler(clock: ManualLeaseClock, *, cpu: int = 8):
    resources = InMemoryResourceLeaseRegistry(clock=clock)
    return in_memory_compute_scheduler(
        _inventory(cpu=cpu),
        resource_authority=resources,
    )


def test_inmemory_exact_retry_reuses_same_fenced_allocation():
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    scheduler = _memory_scheduler(clock)
    first = scheduler.allocate("same", _scope(), _req(), ttl_seconds=10)
    clock.advance(1.0)
    second = scheduler.allocate("same", _scope(), _req(), ttl_seconds=50)

    assert second == first
    assert first.lease_fencing_token == 1
    assert first.lease_expires_at_epoch_s == pytest.approx(110.0)


def test_inmemory_expiry_quarantines_then_recovery_reacquire_fences_old_holder():
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    scheduler = _memory_scheduler(clock, cpu=4)
    first = scheduler.allocate("job", _scope(), _req(), ttl_seconds=5)

    clock.advance(4.0)
    assert scheduler.reconcile_expired() == ()

    clock.advance(1.0)
    with pytest.raises(ComputePhysicalConvergencePending):
        scheduler.reconcile_expired()
    assert scheduler.allocations() == (first,)

    scheduler.recover_release(first)
    clock.advance(1.0)
    second = scheduler.allocate("job", _scope(), _req(), ttl_seconds=5)

    assert second.lease_fencing_token == 2
    assert second.lease_expires_at_epoch_s == pytest.approx(111.0)


def test_inmemory_renew_extends_expiry_without_changing_fencing():
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    scheduler = _memory_scheduler(clock)
    first = scheduler.allocate("job", _scope(), _req(), ttl_seconds=5)

    clock.advance(2.0)
    renewed, = scheduler.renew_many((first,), ttl_seconds=20)

    assert renewed.lease_fencing_token == first.lease_fencing_token
    assert renewed.lease_expires_at_epoch_s == pytest.approx(122.0)

    clock.advance(19.0)
    assert scheduler.reconcile_expired() == ()


def test_sqlite_exact_retry_survives_rebuild(tmp_path):
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    db = tmp_path / "compute.sqlite"
    first_scheduler = SQLiteComputeScheduler(
        db,
        _inventory(),
        clock=clock,
    )
    first = first_scheduler.allocate(
        "same",
        _scope(),
        _req(),
        ttl_seconds=10,
    )

    clock.advance(1.0)
    second_scheduler = SQLiteComputeScheduler(
        db,
        _inventory(),
        clock=clock,
    )
    second = second_scheduler.allocate(
        "same",
        _scope(),
        _req(),
        ttl_seconds=10,
    )

    assert second == first
    assert second.lease_fencing_token == 1


def test_sqlite_expiry_quarantines_then_recovery_reacquire_increments_fencing(
    tmp_path,
):
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    db = tmp_path / "compute.sqlite"
    scheduler = SQLiteComputeScheduler(
        db,
        _inventory(cpu=4),
        clock=clock,
    )
    first = scheduler.allocate("job", _scope(), _req(), ttl_seconds=5)

    clock.advance(5.0)
    with pytest.raises(ComputePhysicalConvergencePending):
        scheduler.reconcile_expired()
    scheduler.recover_release(first)

    clock.advance(1.0)
    rebuilt = SQLiteComputeScheduler(
        db,
        _inventory(cpu=4),
        clock=clock,
    )
    second = rebuilt.allocate("job", _scope(), _req(), ttl_seconds=5)

    assert second.lease_fencing_token == 2


def test_sqlite_candidates_keep_expired_capacity_quarantined_until_recovery(
    tmp_path,
):
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    db = tmp_path / "compute.sqlite"
    scheduler = SQLiteComputeScheduler(
        db,
        _inventory(cpu=4),
        clock=clock,
    )
    old = scheduler.allocate("old", _scope(), _req(), ttl_seconds=1)

    clock.advance(1.0)
    with pytest.raises(ComputePhysicalConvergencePending):
        scheduler.reconcile_expired()
    assert scheduler.candidates(_req(), scope=_scope()) == ()

    scheduler.recover_release(old)
    assert tuple(
        host.host_id
        for host in scheduler.candidates(_req(), scope=_scope())
    ) == ("lease-node",)


def test_same_allocation_id_with_different_contract_conflicts(tmp_path):
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    scheduler = SQLiteComputeScheduler(
        tmp_path / "compute.sqlite",
        _inventory(),
        clock=clock,
    )
    scheduler.allocate(
        "identity",
        _scope(),
        _req(cpu=2),
        ttl_seconds=10,
    )
    clock.advance(1.0)

    with pytest.raises(ValueError, match="identity conflict"):
        scheduler.allocate(
            "identity",
            _scope(),
            _req(cpu=3),
            ttl_seconds=10,
        )
