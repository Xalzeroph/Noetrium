from __future__ import annotations

import pytest

from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeAllocationBatch,
    ComputeAllocationRequest,
    ComputeBatchPlacementStrategy,
    ComputeBatchPlacementUnavailable,
    ComputeHost,
    ComputePlacementUnavailable,
    ComputeRequirement,
)
from noetrium_platform.infrastructure.resources.compute.runtime import (
    InMemoryComputeInventory,
    SQLiteComputeScheduler,
)
from noetrium_platform.infrastructure.resources.lease.runtime import ManualLeaseClock
from tests.resource_compute_support import in_memory_compute_scheduler


def _scope() -> ScopeIdentity:
    return ScopeIdentity(ScopeKind.PROJECT, "atomic-batch-project")


def _inventory() -> InMemoryComputeInventory:
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("host-a", _scope(), 8, 32))
    return inventory


def _batch(second: ComputeRequirement) -> ComputeAllocationBatch:
    scope = _scope()
    return ComputeAllocationBatch(
        "batch-a",
        (
            ComputeAllocationRequest(
                "alloc-b",
                scope,
                second,
            ),
            ComputeAllocationRequest(
                "alloc-a",
                scope,
                ComputeRequirement(cpu_cores=4, memory_bytes=16),
            ),
        ),
    )


def test_compute_batch_canonicalizes_request_order() -> None:
    batch = _batch(ComputeRequirement(cpu_cores=4, memory_bytes=16))
    assert tuple(row.allocation_id for row in batch.requests) == (
        "alloc-a",
        "alloc-b",
    )


@pytest.mark.parametrize("durable", (False, True))
def test_compute_batch_commits_complete_fit(tmp_path, durable: bool) -> None:
    inventory = _inventory()
    scheduler = (
        SQLiteComputeScheduler(
            tmp_path / "compute.sqlite3",
            inventory,
            clock=ManualLeaseClock(),
        )
        if durable
        else in_memory_compute_scheduler(inventory)
    )
    rows = scheduler.allocate_batch(
        _batch(ComputeRequirement(cpu_cores=4, memory_bytes=16))
    )
    assert tuple(row.allocation_id for row in rows) == (
        "alloc-a",
        "alloc-b",
    )
    assert tuple(row.allocation_id for row in scheduler.allocations()) == (
        "alloc-a",
        "alloc-b",
    )


@pytest.mark.parametrize("durable", (False, True))
def test_compute_batch_failure_leaves_no_partial_new_allocation(
    tmp_path,
    durable: bool,
) -> None:
    inventory = _inventory()
    scheduler = (
        SQLiteComputeScheduler(
            tmp_path / "compute.sqlite3",
            inventory,
            clock=ManualLeaseClock(),
        )
        if durable
        else in_memory_compute_scheduler(inventory)
    )
    batch = _batch(ComputeRequirement(cpu_cores=8, memory_bytes=32))

    with pytest.raises(ComputePlacementUnavailable):
        scheduler.allocate_batch(batch)

    assert scheduler.allocations() == ()



def _two_host_inventory(
    *,
    cpu_cores: int = 8,
    memory_bytes: int = 32,
) -> InMemoryComputeInventory:
    inventory = InMemoryComputeInventory()
    inventory.register_host(
        ComputeHost("host-a", _scope(), cpu_cores, memory_bytes)
    )
    inventory.register_host(
        ComputeHost("host-b", _scope(), cpu_cores, memory_bytes)
    )
    return inventory


def _scheduler(tmp_path, durable: bool, inventory: InMemoryComputeInventory):
    return (
        SQLiteComputeScheduler(
            tmp_path / "compute-placement.sqlite3",
            inventory,
            clock=ManualLeaseClock(),
        )
        if durable
        else in_memory_compute_scheduler(inventory)
    )


def _placement_batch(
    strategy: ComputeBatchPlacementStrategy,
    *,
    second: ComputeRequirement | None = None,
) -> ComputeAllocationBatch:
    scope = _scope()
    return ComputeAllocationBatch(
        "placement-batch",
        (
            ComputeAllocationRequest(
                "alloc-a",
                scope,
                ComputeRequirement(cpu_cores=4, memory_bytes=16),
            ),
            ComputeAllocationRequest(
                "alloc-b",
                scope,
                second or ComputeRequirement(cpu_cores=4, memory_bytes=16),
            ),
        ),
        strategy,
    )


@pytest.mark.parametrize("durable", (False, True))
def test_strict_pack_places_entire_batch_on_one_host(
    tmp_path,
    durable: bool,
) -> None:
    scheduler = _scheduler(tmp_path, durable, _two_host_inventory())

    rows = scheduler.allocate_batch(
        _placement_batch(ComputeBatchPlacementStrategy.STRICT_PACK)
    )

    assert len({row.host_id for row in rows}) == 1
    assert tuple(row.allocation_id for row in rows) == ("alloc-a", "alloc-b")


@pytest.mark.parametrize("durable", (False, True))
def test_strict_pack_failure_is_atomic_across_candidate_hosts(
    tmp_path,
    durable: bool,
) -> None:
    scheduler = _scheduler(
        tmp_path,
        durable,
        _two_host_inventory(cpu_cores=4, memory_bytes=16),
    )

    with pytest.raises(ComputeBatchPlacementUnavailable):
        scheduler.allocate_batch(
            _placement_batch(ComputeBatchPlacementStrategy.STRICT_PACK)
        )

    assert scheduler.allocations() == ()


@pytest.mark.parametrize("durable", (False, True))
def test_strict_spread_places_batch_on_distinct_hosts(
    tmp_path,
    durable: bool,
) -> None:
    scheduler = _scheduler(tmp_path, durable, _two_host_inventory())

    rows = scheduler.allocate_batch(
        _placement_batch(ComputeBatchPlacementStrategy.STRICT_SPREAD)
    )

    assert {row.host_id for row in rows} == {"host-a", "host-b"}


@pytest.mark.parametrize("durable", (False, True))
def test_strict_spread_backtracks_around_constrained_bundle(
    tmp_path,
    durable: bool,
) -> None:
    scheduler = _scheduler(tmp_path, durable, _two_host_inventory())

    rows = scheduler.allocate_batch(
        _placement_batch(
            ComputeBatchPlacementStrategy.STRICT_SPREAD,
            second=ComputeRequirement(
                cpu_cores=4,
                memory_bytes=16,
                allowed_host_ids=("host-a",),
            ),
        )
    )
    by_id = {row.allocation_id: row for row in rows}

    assert by_id["alloc-b"].host_id == "host-a"
    assert by_id["alloc-a"].host_id == "host-b"


@pytest.mark.parametrize("durable", (False, True))
def test_strict_spread_failure_leaves_no_partial_batch(
    tmp_path,
    durable: bool,
) -> None:
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("only-host", _scope(), 8, 32))
    scheduler = _scheduler(tmp_path, durable, inventory)

    with pytest.raises(ComputeBatchPlacementUnavailable):
        scheduler.allocate_batch(
            _placement_batch(ComputeBatchPlacementStrategy.STRICT_SPREAD)
        )

    assert scheduler.allocations() == ()
