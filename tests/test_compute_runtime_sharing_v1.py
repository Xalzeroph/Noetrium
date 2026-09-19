from __future__ import annotations

from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeGPU, ComputeHost, ComputeRequirement, GpuDeviceStatus,
    GpuProcessStatus, GpuRuntimeSnapshot, GpuSharingMode,
)
from noetrium_platform.infrastructure.resources.compute.runtime import (
    InMemoryComputeInventory, SQLiteComputeScheduler,
)
from tests.resource_compute_support import in_memory_compute_scheduler


class _Observer:
    def __init__(self, snapshot: GpuRuntimeSnapshot) -> None:
        self.value = snapshot

    def snapshot(self) -> GpuRuntimeSnapshot:
        return self.value


def _scope() -> ScopeIdentity:
    return ScopeIdentity(ScopeKind.PROJECT, "shared-server")


def _inventory() -> InMemoryComputeInventory:
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost(
        "node", _scope(), 32, 256 * 1024**3,
        gpus=(
            ComputeGPU("GPU-idle", 80 * 1024**3, "A100"),
            ComputeGPU("GPU-busy", 80 * 1024**3, "A100"),
        ),
    ))
    return inventory


def _requirement() -> ComputeRequirement:
    return ComputeRequirement(
        cpu_cores=2, memory_bytes=4 * 1024**3, gpu_count=1,
        minimum_gpu_memory_bytes=40 * 1024**3,
        required_gpu_free_memory_bytes=24 * 1024**3,
        max_gpu_utilization_percent=70,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )


def _snapshot(*, idle_free=70 * 1024, busy_free=48 * 1024, busy_util=35):
    return GpuRuntimeSnapshot(
        True,
        devices=(
            GpuDeviceStatus("0", "GPU-idle", "A100", 80 * 1024, 10 * 1024, idle_free, 0),
            GpuDeviceStatus("1", "GPU-busy", "A100", 80 * 1024, 32 * 1024, busy_free, busy_util),
        ),
        processes=(GpuProcessStatus(1234, "GPU-busy", 30 * 1024, "other-user"),),
    )


def test_runtime_scheduler_prefers_idle_gpu_over_eligible_shared_gpu() -> None:
    scheduler = in_memory_compute_scheduler(
        _inventory(), gpu_runtime_observer=_Observer(_snapshot())
    )
    allocation = scheduler.allocate("a", _scope(), _requirement())
    assert allocation.gpu_ids == ("GPU-idle",)


def test_runtime_scheduler_uses_busy_gpu_when_idle_gpu_lacks_required_headroom() -> None:
    scheduler = in_memory_compute_scheduler(
        _inventory(),
        gpu_runtime_observer=_Observer(_snapshot(idle_free=8 * 1024, busy_free=48 * 1024)),
    )
    allocation = scheduler.allocate("a", _scope(), _requirement())
    assert allocation.gpu_ids == ("GPU-busy",)


def test_runtime_scheduler_rejects_shared_gpu_above_utilization_ceiling() -> None:
    scheduler = in_memory_compute_scheduler(
        _inventory(),
        gpu_runtime_observer=_Observer(_snapshot(idle_free=8 * 1024, busy_util=95)),
    )
    try:
        scheduler.allocate("a", _scope(), _requirement())
    except RuntimeError as exc:
        assert "no compute host" in str(exc)
    else:
        raise AssertionError("overloaded shared GPU was admitted")


def test_sqlite_scheduler_uses_same_idle_then_shared_policy(tmp_path) -> None:
    scheduler = SQLiteComputeScheduler(
        tmp_path / "compute.sqlite", _inventory(),
        gpu_runtime_observer=_Observer(_snapshot()),
    )
    first = scheduler.allocate("first", _scope(), _requirement())
    assert first.gpu_ids == ("GPU-idle",)
    second = scheduler.allocate("second", _scope(), _requirement())
    assert second.gpu_ids == ("GPU-busy",)


class _UnavailableObserver:
    def snapshot(self) -> GpuRuntimeSnapshot:
        return GpuRuntimeSnapshot(False, detail="nvidia-smi unavailable")


class _FailingObserver:
    def snapshot(self) -> GpuRuntimeSnapshot:
        raise RuntimeError("observer failed")


def test_shared_gpu_mode_fails_closed_without_live_runtime_facts() -> None:
    for observer in (_UnavailableObserver(), _FailingObserver()):
        scheduler = in_memory_compute_scheduler(_inventory(), gpu_runtime_observer=observer)
        try:
            scheduler.allocate("unknown", _scope(), _requirement())
        except RuntimeError as exc:
            assert "no compute host" in str(exc)
        else:
            raise AssertionError("shared GPU allocation admitted without live usage facts")


class _IncompleteProcessObserver:
    def snapshot(self) -> GpuRuntimeSnapshot:
        value = _snapshot(idle_free=70 * 1024, busy_free=48 * 1024, busy_util=10)
        return GpuRuntimeSnapshot(
            True,
            devices=value.devices,
            processes=(),
            detail="process-query-failed",
            processes_complete=False,
        )


def test_unknown_process_visibility_is_never_ranked_as_idle() -> None:
    scheduler = in_memory_compute_scheduler(
        _inventory(), gpu_runtime_observer=_IncompleteProcessObserver()
    )
    shared = scheduler.allocate("shared-unknown", _scope(), _requirement())
    assert shared.gpu_ids in {("GPU-idle",), ("GPU-busy",)}

    strict = ComputeRequirement(
        cpu_cores=2, memory_bytes=4 * 1024**3, gpu_count=1,
        minimum_gpu_memory_bytes=40 * 1024**3,
        required_gpu_free_memory_bytes=24 * 1024**3,
        max_gpu_utilization_percent=70,
        gpu_sharing_mode=GpuSharingMode.IDLE_ONLY,
    )
    strict_scheduler = in_memory_compute_scheduler(
        _inventory(), gpu_runtime_observer=_IncompleteProcessObserver()
    )
    try:
        strict_scheduler.allocate("strict-unknown", _scope(), strict)
    except RuntimeError as exc:
        assert "no compute host" in str(exc)
    else:
        raise AssertionError("idle-only scheduling trusted incomplete process visibility")
