from __future__ import annotations

import pytest

from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeGPU,
    ComputeHost,
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
    assert scheduler.reconcile_expired(now=103.0) == (first,)
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
    assert scheduler.reconcile_expired(now=103.0)


def test_cpu_only_expiry_does_not_require_gpu_observation() -> None:
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("cpu-node", _scope(), 2, 4096))
    scheduler = in_memory_compute_scheduler(inventory)
    requirement = ComputeRequirement(cpu_cores=2, memory_bytes=1024)
    first = scheduler.allocate(
        "cpu-job",
        _scope(),
        requirement,
        ttl_seconds=1.0,
        now=100.0,
    )
    assert scheduler.reconcile_expired(now=102.0) == (first,)
