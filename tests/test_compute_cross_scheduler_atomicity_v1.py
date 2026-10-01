from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from noetrium_platform.foundation.governance.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeGPU,
    ComputeHost,
    ComputeRequirement,
    GpuDeviceStatus,
    GpuRuntimeSnapshot,
    GpuSharingMode,
)
from noetrium_platform.infrastructure.resources.compute.runtime import (
    ComputeInventory,
    ComputeScheduler,
)
from noetrium_platform.infrastructure.resources.lease.runtime import ManualLeaseClock


class _Observer:
    def snapshot(self) -> GpuRuntimeSnapshot:
        return GpuRuntimeSnapshot(
            True,
            devices=(
                GpuDeviceStatus(
                    "0",
                    "GPU-shared",
                    "A100",
                    80 * 1024,
                    10 * 1024,
                    70 * 1024,
                    10,
                ),
            ),
            processes=(),
            processes_complete=True,
        )


def test_cross_scheduler_gpu_reservations_are_atomic(tmp_path) -> None:
    scope = ScopeIdentity(ScopeKind.PROJECT, "cross-scheduler-gpu-race")
    inventory = ComputeInventory(tmp_path / "inventory.sqlite")
    inventory.register_host(
        ComputeHost(
            "node",
            scope,
            32,
            256 * 1024**3,
            gpus=(ComputeGPU("GPU-shared", 80 * 1024**3, "A100"),),
        )
    )
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    database = tmp_path / "scheduler.sqlite"
    schedulers = (
        ComputeScheduler(
            database,
            inventory,
            clock=clock,
            gpu_runtime_observer=_Observer(),
        ),
        ComputeScheduler(
            database,
            inventory,
            clock=clock,
            gpu_runtime_observer=_Observer(),
        ),
    )
    requirement = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=4 * 1024**3,
        gpu_count=1,
        required_gpu_free_memory_bytes=48 * 1024**3,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )

    for round_id in range(10):
        barrier = Barrier(2)

        def allocate(args):
            scheduler, suffix = args
            barrier.wait(timeout=5.0)
            try:
                allocation = scheduler.allocate(
                    f"race-{round_id}-{suffix}",
                    scope,
                    requirement,
                    ttl_seconds=60.0,
                )
                return scheduler, allocation
            except RuntimeError as exc:
                if "no compute host" not in str(exc):
                    raise
                return scheduler, None

        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = tuple(
                pool.map(
                    allocate,
                    ((schedulers[0], "a"), (schedulers[1], "b")),
                )
            )

        winners = tuple(row for row in rows if row[1] is not None)
        blocked = tuple(row for row in rows if row[1] is None)
        assert len(winners) == 1
        assert len(blocked) == 1
        scheduler, allocation = winners[0]
        assert allocation is not None
        scheduler.release(allocation)
