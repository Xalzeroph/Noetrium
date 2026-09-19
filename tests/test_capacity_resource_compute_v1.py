from __future__ import annotations

from threading import Barrier, Thread
import time

from noetrium_platform.infrastructure.resources.compute.api import ComputeHost, ComputeRequirement
from noetrium_platform.infrastructure.resources.compute.runtime.inventory import InMemoryComputeInventory
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from tests.resource_compute_support import in_memory_compute_scheduler


def _scope(name: str) -> ScopeIdentity:
    return ScopeIdentity(ScopeKind.PROJECT, name)


def test_compute_allocation_never_crosses_requested_scope() -> None:
    first = _scope("first")
    second = _scope("second")
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("a-first", first, 8, 1024))
    inventory.register_host(ComputeHost("b-second", second, 8, 1024))
    scheduler = in_memory_compute_scheduler(inventory)

    allocation = scheduler.allocate(
        "second-allocation", second, ComputeRequirement(cpu_cores=1, memory_bytes=1)
    )
    assert inventory.host(allocation.host_id).scope == second


class _SlowInventory(InMemoryComputeInventory):
    def list_hosts(self, *, scope=None):
        rows = super().list_hosts(scope=scope)
        time.sleep(0.05)
        return rows


def test_compute_allocation_is_linearizable_under_thread_contention() -> None:
    scope = _scope("shared")
    inventory = _SlowInventory()
    inventory.register_host(ComputeHost("host", scope, 1, 1))
    scheduler = in_memory_compute_scheduler(inventory)
    start = Barrier(3)
    allocations = []
    errors = []

    def allocate(index: int) -> None:
        start.wait(timeout=2)
        try:
            allocations.append(
                scheduler.allocate(
                    f"allocation-{index}", scope, ComputeRequirement(cpu_cores=1, memory_bytes=1)
                )
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [Thread(target=allocate, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    start.wait(timeout=2)
    for thread in threads:
        thread.join(timeout=3)

    assert all(not thread.is_alive() for thread in threads)
    assert len(allocations) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert sum(row.cpu_cores for row in scheduler.allocations()) == 1
