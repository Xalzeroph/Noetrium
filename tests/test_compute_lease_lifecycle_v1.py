from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import ComputeHost, ComputeRequirement
from noetrium_platform.infrastructure.resources.compute.runtime import InMemoryComputeInventory, SQLiteComputeScheduler
from tests.resource_compute_support import in_memory_compute_scheduler


def _scope():
    return ScopeIdentity(ScopeKind.PROJECT, "lease-project")


def _inventory(cpu=8):
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("lease-node", _scope(), cpu, 1024))
    return inventory


def _req(cpu=4):
    return ComputeRequirement(cpu_cores=cpu, memory_bytes=128)


def test_inmemory_exact_retry_reuses_same_fenced_allocation():
    scheduler = in_memory_compute_scheduler(_inventory())
    first = scheduler.allocate("same", _scope(), _req(), ttl_seconds=10, now=100)
    second = scheduler.allocate("same", _scope(), _req(), ttl_seconds=50, now=101)
    assert second == first
    assert first.lease_fencing_token == 1
    assert first.lease_expires_at_epoch_s == 110


def test_inmemory_expiry_releases_capacity_and_reacquire_fences_old_holder():
    scheduler = in_memory_compute_scheduler(_inventory(cpu=4))
    first = scheduler.allocate("job", _scope(), _req(), ttl_seconds=5, now=100)
    assert scheduler.reconcile_expired(now=104) == ()
    expired = scheduler.reconcile_expired(now=105)
    assert expired == (first,)
    second = scheduler.allocate("job", _scope(), _req(), ttl_seconds=5, now=106)
    assert second.lease_fencing_token == 2
    assert second.lease_expires_at_epoch_s == 111


def test_inmemory_renew_extends_expiry_without_changing_fencing():
    scheduler = in_memory_compute_scheduler(_inventory())
    first = scheduler.allocate("job", _scope(), _req(), ttl_seconds=5, now=100)
    renewed, = scheduler.renew_many(("job",), ttl_seconds=20, now=102)
    assert renewed.lease_fencing_token == first.lease_fencing_token
    assert renewed.lease_expires_at_epoch_s == 122
    assert scheduler.reconcile_expired(now=121) == ()


def test_sqlite_exact_retry_survives_rebuild(tmp_path):
    db = tmp_path / "compute.sqlite"
    first_scheduler = SQLiteComputeScheduler(db, _inventory())
    first = first_scheduler.allocate("same", _scope(), _req(), ttl_seconds=10, now=100)
    second_scheduler = SQLiteComputeScheduler(db, _inventory())
    second = second_scheduler.allocate("same", _scope(), _req(), ttl_seconds=10, now=101)
    assert second == first
    assert second.lease_fencing_token == 1


def test_sqlite_expired_reacquire_increments_durable_fencing(tmp_path):
    db = tmp_path / "compute.sqlite"
    scheduler = SQLiteComputeScheduler(db, _inventory(cpu=4))
    first = scheduler.allocate("job", _scope(), _req(), ttl_seconds=5, now=100)
    assert scheduler.reconcile_expired(now=105) == (first,)
    rebuilt = SQLiteComputeScheduler(db, _inventory(cpu=4))
    second = rebuilt.allocate("job", _scope(), _req(), ttl_seconds=5, now=106)
    assert second.lease_fencing_token == 2


def test_sqlite_candidates_ignore_expired_without_mutating_authority(tmp_path):
    db = tmp_path / "compute.sqlite"
    scheduler = SQLiteComputeScheduler(db, _inventory(cpu=4))
    scheduler.allocate("old", _scope(), _req(), ttl_seconds=1, now=1)
    # candidate projection must not delete durable rows; it only projects live capacity.
    # Monkeypatching time is deliberately avoided; explicit reconciliation proves mutation.
    assert scheduler.reconcile_expired(now=2)
    assert tuple(host.host_id for host in scheduler.candidates(_req(), scope=_scope())) == ("lease-node",)


def test_same_allocation_id_with_different_contract_conflicts(tmp_path):
    scheduler = SQLiteComputeScheduler(tmp_path / "compute.sqlite", _inventory())
    scheduler.allocate("identity", _scope(), _req(cpu=2), ttl_seconds=10, now=100)
    try:
        scheduler.allocate("identity", _scope(), _req(cpu=3), ttl_seconds=10, now=101)
    except ValueError as exc:
        assert "identity conflict" in str(exc)
    else:
        raise AssertionError("mismatched allocation contract was silently reused")
