import pytest

from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeBindingProof,
    ComputeHost,
    ComputeRequirement,
)
from noetrium_platform.infrastructure.resources.compute.runtime import (
    ComputePhysicalConvergencePending,
    InMemoryComputeInventory,
    SQLiteComputeScheduler,
)
from noetrium_platform.infrastructure.resources.lease.api import ResourceLeaseConflict
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


def _proof(
    allocation,
    *,
    binder: str,
    observed_at: float = 101.0,
):
    return ComputeBindingProof(
        allocation_id=allocation.allocation_id,
        host_id=allocation.host_id,
        gpu_ids=allocation.gpu_ids,
        lease_fencing_token=allocation.lease_fencing_token,
        binder_identity_digest=binder,
        observed_at_epoch_s=observed_at,
        evidence_ref=f"runtime:{binder[:8]}",
    )


def test_inmemory_compute_binding_is_idempotent_and_rebind_is_cas_fenced():
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    scheduler = _memory_scheduler(clock)
    allocation = scheduler.allocate(
        "bound",
        _scope(),
        _req(),
        ttl_seconds=30,
    )
    first_proof = _proof(allocation, binder="a" * 64)
    first = scheduler.confirm_bound(first_proof)
    assert first.is_bound
    assert scheduler.confirm_bound(first_proof) == first

    second_proof = _proof(allocation, binder="b" * 64, observed_at=102.0)
    with pytest.raises(ResourceLeaseConflict, match="already bound"):
        scheduler.confirm_bound(second_proof)

    second = scheduler.replace_bound(
        second_proof,
        previous_binding_proof_digest=first_proof.digest(),
    )
    assert second.binding_binder_identity_digest == "b" * 64
    with pytest.raises(ResourceLeaseConflict, match="lost prior generation"):
        scheduler.replace_bound(
            _proof(allocation, binder="c" * 64, observed_at=103.0),
            previous_binding_proof_digest=first_proof.digest(),
        )


def test_inmemory_expired_compute_generation_cannot_be_bound():
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    scheduler = _memory_scheduler(clock)
    allocation = scheduler.allocate(
        "expired-bind",
        _scope(),
        _req(),
        ttl_seconds=1,
    )
    clock.advance(1.0)
    with pytest.raises(ResourceLeaseConflict, match="active lease authority"):
        scheduler.confirm_bound(
            _proof(allocation, binder="d" * 64, observed_at=102.0)
        )


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


def test_sqlite_compute_binding_cas_survives_authority_rebuild(tmp_path):
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    database = tmp_path / "compute-binding.sqlite"
    scheduler = SQLiteComputeScheduler(
        database,
        _inventory(),
        clock=clock,
    )
    allocation = scheduler.allocate(
        "bound",
        _scope(),
        _req(),
        ttl_seconds=30,
    )
    first_proof = _proof(allocation, binder="a" * 64)
    first = scheduler.confirm_bound(first_proof)

    rebuilt = SQLiteComputeScheduler(
        database,
        _inventory(),
        clock=clock,
    )
    assert rebuilt.allocations() == (first,)
    second_proof = _proof(allocation, binder="b" * 64, observed_at=102.0)
    second = rebuilt.replace_bound(
        second_proof,
        previous_binding_proof_digest=first_proof.digest(),
    )
    assert second.binding_binder_identity_digest == "b" * 64

    restarted = SQLiteComputeScheduler(
        database,
        _inventory(),
        clock=clock,
    )
    assert restarted.allocations() == (second,)
    with pytest.raises(ResourceLeaseConflict, match="lost prior generation"):
        restarted.replace_bound(
            _proof(allocation, binder="c" * 64, observed_at=103.0),
            previous_binding_proof_digest=first_proof.digest(),
        )


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
