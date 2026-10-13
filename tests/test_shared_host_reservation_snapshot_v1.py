from __future__ import annotations

from noetrium_platform.foundation.kernel.concurrency.api import ExecutionLaneKind

from pathlib import Path

from resource_test_support import make_resource_competition_reservations
from noetrium_platform.composition.shared_host_pressure import (
    ResourceCompetitionDemand,
    _StorageReservation,
)


def test_authority_reservation_transaction_reuses_one_sparse_snapshot(
    tmp_path: Path,
) -> None:
    authority, lease, reservations = make_resource_competition_reservations(tmp_path)
    demand = ResourceCompetitionDemand(
        cpu_cores_per_permit=4,
        memory_bytes_per_permit=128,
        pids_per_permit=2,
        fds_per_permit=3,
    )
    storage = (
        _StorageReservation("cap-a", 10, 1),
        _StorageReservation("cap-b", 20, 2),
    )
    tokens = reservations.reserve(
        demand,
        lane_kind=ExecutionLaneKind.BLOCKING_IO,
        permit_count=1,
        storage=storage,
    )

    calls = 0
    original = authority.snapshot_for_resource_keys

    def counted(resource_keys):
        nonlocal calls
        calls += 1
        return original(resource_keys)

    authority.snapshot_for_resource_keys = counted  # type: ignore[method-assign]
    with reservations.lock:
        reserved = reservations.reserved_demand()
        cap_a = reservations.reserved_storage_for("cap-a")
        cap_b = reservations.reserved_storage_for("cap-b")
        assert reservations.reserved_demand() == reserved
        assert reservations.reserved_storage_for("cap-a") == cap_a
        assert reservations.reserved_storage_for("cap-b") == cap_b

    assert calls == 1
    assert reserved.cpu_cores_per_permit == 4
    assert reserved.memory_bytes_per_permit == 128
    assert reserved.pids_per_permit == 2
    assert reserved.fds_per_permit == 3
    assert cap_a == (10, 1)
    assert cap_b == (20, 2)

    reservations.release(tokens[0])
    reservations.close()
    authority.release_lease(lease)


def test_one_authority_claim_per_permit_preserves_affine_release(
    tmp_path: Path,
) -> None:
    authority, lease, reservations = make_resource_competition_reservations(tmp_path)
    demand = ResourceCompetitionDemand(memory_bytes_per_permit=256)
    tokens = reservations.reserve(
        demand,
        lane_kind=ExecutionLaneKind.BLOCKING_IO,
        permit_count=4,
        storage=(),
    )

    assert len(tokens) == 4
    assert len({token.claim_id for token in tokens}) == 4
    assert reservations.reserved_demand().memory_bytes_per_permit == 1024

    reservations.release(tokens[1])
    assert reservations.reserved_demand().memory_bytes_per_permit == 768
    reservations.release(tokens[3])
    assert reservations.reserved_demand().memory_bytes_per_permit == 512
    reservations.release(tokens[0])
    reservations.release(tokens[2])
    assert reservations.reserved_demand() == ResourceCompetitionDemand()

    assert authority.snapshot_for_holder(
        reservations._holder_key  # exact sparse test locus
    ).claims == ()
    reservations.close()
    authority.release_lease(lease)




def test_reservation_release_does_not_take_global_admission_mutex(
    tmp_path: Path,
) -> None:
    authority, lease, reservations = make_resource_competition_reservations(tmp_path)
    tokens = reservations.reserve(
        ResourceCompetitionDemand(memory_bytes_per_permit=64),
        lane_kind=ExecutionLaneKind.BLOCKING_IO,
        permit_count=1,
        storage=(),
    )
    original_guard = reservations._global_guard

    class RejectGlobalGuard:
        def __enter__(self):
            raise AssertionError("monotone reservation release took global admission mutex")

        def __exit__(self, exc_type, exc, traceback):
            return False

    reservations._global_guard = RejectGlobalGuard()
    try:
        reservations.release(tokens[0])
    finally:
        reservations._global_guard = original_guard

    assert reservations.reserved_demand() == ResourceCompetitionDemand()
    reservations.close()
    authority.release_lease(lease)

def test_many_permits_reuse_one_stable_reservation_generation(
    tmp_path: Path,
) -> None:
    authority, lease, reservations = make_resource_competition_reservations(tmp_path)
    generation_count = len(authority.snapshot().generations)
    tokens = reservations.reserve(
        ResourceCompetitionDemand(memory_bytes_per_permit=1),
        lane_kind=ExecutionLaneKind.BLOCKING_IO,
        permit_count=32,
        storage=(),
    )
    snapshot = authority.snapshot_for_resource_keys(
        frozenset({reservations._resource_key})
    )
    assert len(snapshot.generations) == 1
    assert len(snapshot.claims) == 32
    assert len({token.claim_id for token in tokens}) == 32
    assert {token.resource_key for token in tokens} == {
        reservations._resource_key
    }
    assert len(authority.snapshot().generations) == generation_count
    for token in tokens:
        reservations.release(token)
    assert reservations.reserved_demand() == ResourceCompetitionDemand()
    reservations.close()
    authority.release_lease(lease)


def test_independent_owners_share_one_host_boot_reservation_cut(
    tmp_path: Path,
) -> None:
    from uuid import uuid4
    from noetrium_platform.composition.shared_host_pressure import (
        ResourceCompetitionReservations,
    )
    from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE

    authority, first_lease, first = make_resource_competition_reservations(tmp_path)
    owner = uuid4().hex
    second_lease = authority.acquire_ttl_lease(
        lease_id="test-resource-competition-owner:" + owner,
        resource_key="test-resource-competition-owner:" + owner,
        holder_key="test-resource-competition-owner:" + owner,
        owner_scope=PLATFORM_SCOPE,
        ttl_seconds=30.0,
        metadata={"kind": "resource-competition-owner-test"},
    )
    second = ResourceCompetitionReservations(
        authority,
        second_lease,
        coordination_directory=tmp_path / "coordination",
    )
    assert first._resource_key == second._resource_key
    assert first._resource_generation == second._resource_generation

    left = first.reserve(
        ResourceCompetitionDemand(memory_bytes_per_permit=3),
        lane_kind=ExecutionLaneKind.BLOCKING_IO,
        permit_count=1,
        storage=(),
    )[0]
    assert second.reserved_demand().memory_bytes_per_permit == 3

    right = second.reserve(
        ResourceCompetitionDemand(memory_bytes_per_permit=5),
        lane_kind=ExecutionLaneKind.BLOCKING_IO,
        permit_count=1,
        storage=(),
    )[0]
    assert first.reserved_demand().memory_bytes_per_permit == 8

    first.release(left)
    assert second.reserved_demand().memory_bytes_per_permit == 5
    second.release(right)
    assert first.reserved_demand() == ResourceCompetitionDemand()

    second.close()
    first.close()
    authority.release_lease(second_lease)
    authority.release_lease(first_lease)


def test_reservation_filesystem_contains_only_stateless_linearization_lock(
    tmp_path: Path,
) -> None:
    authority, lease, reservations = make_resource_competition_reservations(tmp_path)
    tokens = reservations.reserve(
        ResourceCompetitionDemand(memory_bytes_per_permit=64),
        lane_kind=ExecutionLaneKind.BLOCKING_IO,
        permit_count=1,
        storage=(),
    )
    coordination = tmp_path / "coordination"
    names = {path.name for path in coordination.iterdir()}
    assert "reservation-linearization.lock" in names
    assert not any(name.startswith("owner-") for name in names)
    assert not any(name.endswith(".json") for name in names)

    reservations.release(tokens[0])
    reservations.close()
    authority.release_lease(lease)
