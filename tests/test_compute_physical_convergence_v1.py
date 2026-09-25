from __future__ import annotations

import pytest

from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeGPU,
    ComputeHost,
    ComputePlacementUnavailable,
    ComputeRequirement,
    GpuDeviceStatus,
    GpuProcessStatus,
    GpuRuntimeSnapshot,
    GpuSharingMode,
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


class MutableGpuObserver:
    def __init__(self) -> None:
        self.busy = False
        self.complete = True

    def snapshot(self) -> GpuRuntimeSnapshot:
        processes = (
            (GpuProcessStatus(4242, "GPU-0", 4096, "surviving-owner"),)
            if self.busy
            else ()
        )
        return GpuRuntimeSnapshot(
            True,
            devices=(
                GpuDeviceStatus(
                    "0",
                    "GPU-0",
                    "test-gpu",
                    81920,
                    4096 if self.busy else 0,
                    77824 if self.busy else 81920,
                    10 if self.busy else 0,
                ),
            ),
            processes=processes,
            processes_complete=self.complete,
        )


def _scope() -> ScopeIdentity:
    return ScopeIdentity(ScopeKind.PROJECT, "gpu-crash-window")


def _inventory() -> InMemoryComputeInventory:
    inventory = InMemoryComputeInventory()
    inventory.register_host(
        ComputeHost(
            "gpu-node",
            _scope(),
            8,
            64 * 1024**3,
            gpus=(ComputeGPU("GPU-0", 80 * 1024**3, "test-gpu"),),
        )
    )
    return inventory


def _clock() -> ManualLeaseClock:
    return ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )


def _scheduler(
    tmp_path,
    *,
    durable: bool,
    inventory: InMemoryComputeInventory,
    observer=None,
    filename: str,
):
    clock = _clock()
    if durable:
        scheduler = SQLiteComputeScheduler(
            tmp_path / filename,
            inventory,
            clock=clock,
            gpu_runtime_observer=observer,
        )
    else:
        scheduler = in_memory_compute_scheduler(
            inventory,
            resource_authority=InMemoryResourceLeaseRegistry(clock=clock),
            gpu_runtime_observer=observer,
        )
    return scheduler, clock


def _requirement() -> ComputeRequirement:
    return ComputeRequirement(
        cpu_cores=1,
        memory_bytes=1024,
        gpu_count=1,
        minimum_gpu_memory_bytes=1,
        required_gpu_free_memory_bytes=1,
        max_gpu_utilization_percent=100,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )


@pytest.mark.parametrize("durable", [False, True])
def test_expired_gpu_lease_does_not_release_capacity_while_process_survives(
    tmp_path,
    durable: bool,
) -> None:
    observer = MutableGpuObserver()
    scheduler = (
        SQLiteComputeScheduler(
            tmp_path / "compute-quarantine.sqlite",
            _inventory(),
            gpu_runtime_observer=observer,
        )
        if durable
        else in_memory_compute_scheduler(
            _inventory(),
            gpu_runtime_observer=observer,
        )
    )
    first = scheduler.allocate(
        "gpu-job",
        _scope(),
        _requirement(),
        ttl_seconds=1.0,
        now=100.0,
    )

    observer.busy = True
    with pytest.raises(
        ComputePhysicalConvergencePending,
        match="physical convergence pending",
    ):
        scheduler.reconcile_expired(now=102.0)

    with pytest.raises(ComputePhysicalConvergencePending):
        scheduler.allocate(
            "replacement",
            _scope(),
            _requirement(),
            ttl_seconds=30.0,
            now=102.0,
        )

    observer.busy = False
    with pytest.raises(ComputePhysicalConvergencePending):
        scheduler.reconcile_expired(now=103.0)

    scheduler.recover_release(first)
    replacement = scheduler.allocate(
        "gpu-job",
        _scope(),
        _requirement(),
        ttl_seconds=30.0,
        now=104.0,
    )
    assert replacement.gpu_ids == ("GPU-0",)
    assert replacement.lease_fencing_token > first.lease_fencing_token


@pytest.mark.parametrize("durable", [False, True])
def test_normal_release_refuses_live_gpu_process(
    tmp_path,
    durable: bool,
) -> None:
    observer = MutableGpuObserver()
    scheduler = (
        SQLiteComputeScheduler(
            tmp_path / "compute-normal-release.sqlite",
            _inventory(),
            gpu_runtime_observer=observer,
        )
        if durable
        else in_memory_compute_scheduler(
            _inventory(),
            gpu_runtime_observer=observer,
        )
    )
    allocation = scheduler.allocate(
        "gpu-job",
        _scope(),
        _requirement(),
        ttl_seconds=30.0,
        now=100.0,
    )
    observer.busy = True
    with pytest.raises(ComputePhysicalConvergencePending):
        scheduler.release(allocation)
    assert scheduler.allocations() == (allocation,)

    observer.busy = False
    scheduler.release(allocation)
    assert scheduler.allocations() == ()


@pytest.mark.parametrize("durable", [False, True])
def test_recovery_release_refuses_live_orphan_gpu_process(
    tmp_path,
    durable: bool,
) -> None:
    observer = MutableGpuObserver()
    scheduler = (
        SQLiteComputeScheduler(
            tmp_path / "compute-recovery-gpu.sqlite",
            _inventory(),
            gpu_runtime_observer=observer,
        )
        if durable
        else in_memory_compute_scheduler(
            _inventory(),
            gpu_runtime_observer=observer,
        )
    )
    allocation = scheduler.allocate(
        "gpu-job",
        _scope(),
        _requirement(),
        ttl_seconds=30.0,
        now=100.0,
    )

    observer.busy = True
    with pytest.raises(
        ComputePhysicalConvergencePending,
        match="physical convergence pending",
    ):
        scheduler.recover_release(allocation)
    assert scheduler.allocations() == (allocation,)

    observer.busy = False
    scheduler.recover_release(allocation)
    assert scheduler.allocations() == ()


@pytest.mark.parametrize("durable", [False, True])
def test_recovery_release_fails_closed_when_gpu_visibility_is_unknown(
    tmp_path,
    durable: bool,
) -> None:
    observer = MutableGpuObserver()
    scheduler = (
        SQLiteComputeScheduler(
            tmp_path / "compute-recovery-unknown.sqlite",
            _inventory(),
            gpu_runtime_observer=observer,
        )
        if durable
        else in_memory_compute_scheduler(
            _inventory(),
            gpu_runtime_observer=observer,
        )
    )
    allocation = scheduler.allocate(
        "gpu-job",
        _scope(),
        _requirement(),
        ttl_seconds=30.0,
        now=100.0,
    )
    observer.complete = False
    with pytest.raises(ComputePhysicalConvergencePending):
        scheduler.recover_release(allocation)
    assert scheduler.allocations() == (allocation,)


@pytest.mark.parametrize("durable", [False, True])
def test_expired_gpu_lease_fails_closed_when_process_visibility_is_incomplete(
    tmp_path,
    durable: bool,
) -> None:
    observer = MutableGpuObserver()
    scheduler = (
        SQLiteComputeScheduler(
            tmp_path / "compute-unknown.sqlite",
            _inventory(),
            gpu_runtime_observer=observer,
        )
        if durable
        else in_memory_compute_scheduler(
            _inventory(),
            gpu_runtime_observer=observer,
        )
    )
    scheduler.allocate(
        "gpu-job",
        _scope(),
        _requirement(),
        ttl_seconds=1.0,
        now=100.0,
    )

    observer.complete = False
    with pytest.raises(ComputePhysicalConvergencePending):
        scheduler.reconcile_expired(now=102.0)

    observer.complete = True
    with pytest.raises(ComputePhysicalConvergencePending):
        scheduler.reconcile_expired(now=103.0)


@pytest.mark.parametrize("durable", [False, True])
def test_cpu_only_expiry_quarantines_capacity_until_exclusive_recovery(
    tmp_path,
    durable: bool,
) -> None:
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("cpu-node", _scope(), 2, 4096))
    scheduler = (
        SQLiteComputeScheduler(tmp_path / "cpu-quarantine.sqlite", inventory)
        if durable
        else in_memory_compute_scheduler(inventory)
    )
    requirement = ComputeRequirement(cpu_cores=2, memory_bytes=1024)
    first = scheduler.allocate(
        "cpu-job",
        _scope(),
        requirement,
        ttl_seconds=1.0,
        now=100.0,
    )
    with pytest.raises(ComputePhysicalConvergencePending):
        scheduler.reconcile_expired(now=102.0)
    assert scheduler.allocations() == (first,)
    with pytest.raises(ComputePlacementUnavailable):
        scheduler.allocate(
            "replacement",
            _scope(),
            requirement,
            ttl_seconds=30.0,
            now=103.0,
        )

    scheduler.recover_release(first)
    replacement = scheduler.allocate(
        "replacement",
        _scope(),
        requirement,
        ttl_seconds=30.0,
        now=104.0,
    )
    assert replacement.host_id == "cpu-node"



@pytest.mark.parametrize("durable", [False, True])
def test_quarantined_compute_generation_does_not_globally_block_spare_capacity(
    tmp_path,
    durable: bool,
) -> None:
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("cpu-wide", _scope(), 4, 8192))
    scheduler = (
        SQLiteComputeScheduler(tmp_path / "compute-spare.sqlite", inventory)
        if durable
        else in_memory_compute_scheduler(inventory)
    )
    requirement = ComputeRequirement(cpu_cores=1, memory_bytes=1024)
    first = scheduler.allocate(
        "stale",
        _scope(),
        requirement,
        ttl_seconds=1.0,
        now=100.0,
    )
    with pytest.raises(ComputePhysicalConvergencePending):
        scheduler.reconcile_expired(now=102.0)

    second = scheduler.allocate(
        "independent",
        _scope(),
        requirement,
        ttl_seconds=30.0,
        now=103.0,
    )
    assert second.host_id == first.host_id
    assert {row.allocation_id for row in scheduler.allocations()} == {
        "stale",
        "independent",
    }


@pytest.mark.parametrize("durable", [False, True])
def test_stale_recovery_release_cannot_delete_replacement_generation(
    tmp_path,
    durable: bool,
) -> None:
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("cpu-reuse", _scope(), 2, 4096))
    scheduler = (
        SQLiteComputeScheduler(tmp_path / "compute-reuse.sqlite", inventory)
        if durable
        else in_memory_compute_scheduler(inventory)
    )
    requirement = ComputeRequirement(cpu_cores=1, memory_bytes=1024)
    first = scheduler.allocate(
        "same",
        _scope(),
        requirement,
        ttl_seconds=1.0,
        now=100.0,
    )
    with pytest.raises(ComputePhysicalConvergencePending):
        scheduler.reconcile_expired(now=102.0)
    scheduler.recover_release(first)

    replacement = scheduler.allocate(
        "same",
        _scope(),
        requirement,
        ttl_seconds=30.0,
        now=103.0,
    )
    assert replacement.lease_fencing_token > first.lease_fencing_token

    with pytest.raises(ResourceLeaseConflict):
        scheduler.recover_release(first)

    assert scheduler.allocations() == (replacement,)
