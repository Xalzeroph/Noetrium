from __future__ import annotations

import pytest

from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeAllocationBatch,
    ComputeAllocationRequest,
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
