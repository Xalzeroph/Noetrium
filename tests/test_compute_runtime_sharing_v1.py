from __future__ import annotations

import pytest

from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeBindingProof, ComputeGPU, ComputeHost, ComputeRequirement, GpuDeviceStatus,
    GpuProcessStatus, GpuRuntimeSnapshot, GpuSharingMode,
)
from noetrium_platform.infrastructure.resources.compute.runtime import ComputeScheduler
from tests.resource_compute_support import TestComputeInventory, compute_scheduler
from noetrium_platform.infrastructure.resources.lease.runtime import ManualLeaseClock


class _Observer:
    def __init__(self, snapshot: GpuRuntimeSnapshot) -> None:
        self.value = snapshot

    def snapshot(self) -> GpuRuntimeSnapshot:
        return self.value


def _scope() -> ScopeIdentity:
    return ScopeIdentity(ScopeKind.PROJECT, "shared-server")


def _inventory() -> TestComputeInventory:
    inventory = TestComputeInventory()
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


def _snapshot(
    *,
    idle_free=70 * 1024,
    busy_free=48 * 1024,
    busy_util=35,
    idle_total=80 * 1024,
    busy_total=80 * 1024,
):
    return GpuRuntimeSnapshot(
        True,
        devices=(
            GpuDeviceStatus("0", "GPU-idle", "A100", idle_total, 10 * 1024, idle_free, 0),
            GpuDeviceStatus("1", "GPU-busy", "A100", busy_total, 32 * 1024, busy_free, busy_util),
        ),
        processes=(GpuProcessStatus(1234, "GPU-busy", 30 * 1024, "other-user"),),
    )


def test_runtime_scheduler_prefers_idle_gpu_over_eligible_shared_gpu() -> None:
    scheduler = compute_scheduler(
        _inventory(), gpu_runtime_observer=_Observer(_snapshot())
    )
    allocation = scheduler.allocate("a", _scope(), _requirement())
    assert allocation.gpu_ids == ("GPU-idle",)


def test_runtime_scheduler_uses_busy_gpu_when_idle_gpu_lacks_required_headroom() -> None:
    scheduler = compute_scheduler(
        _inventory(),
        gpu_runtime_observer=_Observer(_snapshot(idle_free=8 * 1024, busy_free=48 * 1024)),
    )
    allocation = scheduler.allocate("a", _scope(), _requirement())
    assert allocation.gpu_ids == ("GPU-busy",)


def test_runtime_scheduler_honors_explicit_gpu_exclusion() -> None:
    scheduler = compute_scheduler(
        _inventory(), gpu_runtime_observer=_Observer(_snapshot())
    )
    allocation = scheduler.allocate(
        "excluded-idle",
        _scope(),
        _requirement(),
        excluded_gpus=frozenset({("node", "GPU-idle")}),
    )
    assert allocation.gpu_ids == ("GPU-busy",)


def test_runtime_scheduler_revalidates_exact_unbound_gpu_after_external_capacity_drift() -> None:
    observer = _Observer(_snapshot())
    scheduler = compute_scheduler(_inventory(), gpu_runtime_observer=observer)
    requirement = _requirement()
    allocation = scheduler.allocate("drift", _scope(), requirement)
    assert allocation.gpu_ids == ("GPU-idle",)
    assert scheduler.unbound_placement_satisfies(allocation, requirement) is True

    observer.value = _snapshot(idle_free=8 * 1024, busy_free=48 * 1024)
    assert scheduler.unbound_placement_satisfies(allocation, requirement) is False


def _single_gpu_inventory() -> TestComputeInventory:
    inventory = TestComputeInventory()
    inventory.register_host(
        ComputeHost(
            "single-node",
            _scope(),
            32,
            256 * 1024**3,
            gpus=(ComputeGPU("GPU-shared", 80 * 1024**3, "A100"),),
        )
    )
    return inventory


def _single_gpu_snapshot(*, free_gib: int = 70) -> GpuRuntimeSnapshot:
    return GpuRuntimeSnapshot(
        True,
        devices=(
            GpuDeviceStatus(
                "0",
                "GPU-shared",
                "A100",
                80 * 1024,
                (80 - free_gib) * 1024,
                free_gib * 1024,
                10,
            ),
        ),
        processes=(),
        processes_complete=True,
    )


def test_shared_noetrium_allocations_pack_same_gpu_by_unbound_vram_reservation() -> None:
    observer = _Observer(_single_gpu_snapshot(free_gib=70))
    scheduler = compute_scheduler(
        _single_gpu_inventory(),
        gpu_runtime_observer=observer,
    )
    requirement = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=4 * 1024**3,
        gpu_count=1,
        required_gpu_free_memory_bytes=24 * 1024**3,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )

    first = scheduler.allocate("shared-a", _scope(), requirement)
    second = scheduler.allocate("shared-b", _scope(), requirement)

    assert first.gpu_ids == ("GPU-shared",)
    assert second.gpu_ids == ("GPU-shared",)
    assert first.gpu_memory_reservation_bytes == (24 * 1024**3,)
    assert second.gpu_memory_reservation_bytes == (24 * 1024**3,)

    try:
        scheduler.allocate("shared-c", _scope(), requirement)
    except RuntimeError as exc:
        assert "no compute host" in str(exc)
    else:
        raise AssertionError(
            "third shared allocation reused VRAM already reserved by unbound launches"
        )


def test_bound_shared_gpu_keeps_logical_vram_reservation_until_release(tmp_path) -> None:
    # Simulate telemetry lag: after binding, nvidia-smi still reports the same
    # pre-bind free VRAM. Logical capacity commitments must remain authoritative.
    observer = _Observer(_single_gpu_snapshot(free_gib=70))
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    database = tmp_path / "bound-shared-gpu.sqlite"
    requirement = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=4 * 1024**3,
        gpu_count=1,
        required_gpu_free_memory_bytes=48 * 1024**3,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )
    scheduler = ComputeScheduler(
        database,
        _single_gpu_inventory(),
        clock=clock,
        gpu_runtime_observer=observer,
    )
    first = scheduler.allocate(
        "bound-a",
        _scope(),
        requirement,
        ttl_seconds=60,
    )
    bound = scheduler.confirm_bound(
        ComputeBindingProof(
            allocation_id=first.allocation_id,
            host_id=first.host_id,
            gpu_ids=first.gpu_ids,
            lease_fencing_token=first.lease_fencing_token,
            binder_identity_digest="a" * 64,
            observed_at_epoch_s=101.0,
            evidence_ref="gpu-binding:bound-a",
        )
    )
    assert bound.is_bound

    rebuilt = ComputeScheduler(
        database,
        _single_gpu_inventory(),
        clock=clock,
        gpu_runtime_observer=observer,
    )
    with pytest.raises(RuntimeError, match="no compute host"):
        rebuilt.allocate(
            "bound-b",
            _scope(),
            requirement,
            ttl_seconds=60,
        )


def test_sqlite_shared_gpu_reservations_survive_scheduler_restart(tmp_path) -> None:
    observer = _Observer(_single_gpu_snapshot(free_gib=70))
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    database = tmp_path / "shared-gpu.sqlite"
    requirement = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=4 * 1024**3,
        gpu_count=1,
        required_gpu_free_memory_bytes=24 * 1024**3,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )
    first_scheduler = ComputeScheduler(
        database,
        _single_gpu_inventory(),
        clock=clock,
        gpu_runtime_observer=observer,
    )
    first_scheduler.allocate(
        "shared-a",
        _scope(),
        requirement,
        ttl_seconds=60,
    )
    first_scheduler.allocate(
        "shared-b",
        _scope(),
        requirement,
        ttl_seconds=60,
    )

    rebuilt = ComputeScheduler(
        database,
        _single_gpu_inventory(),
        clock=clock,
        gpu_runtime_observer=observer,
    )
    try:
        rebuilt.allocate(
            "shared-c",
            _scope(),
            requirement,
            ttl_seconds=60,
        )
    except RuntimeError as exc:
        assert "no compute host" in str(exc)
    else:
        raise AssertionError(
            "durable scheduler lost unbound shared-GPU VRAM reservations"
        )


def test_idle_only_allocation_blocks_shared_noetrium_reoccupation() -> None:
    scheduler = compute_scheduler(
        _single_gpu_inventory(),
        gpu_runtime_observer=_Observer(_single_gpu_snapshot()),
    )
    exclusive = ComputeRequirement(
        cpu_cores=1,
        memory_bytes=1,
        gpu_count=1,
        gpu_sharing_mode=GpuSharingMode.IDLE_ONLY,
    )
    shared = ComputeRequirement(
        cpu_cores=1,
        memory_bytes=1,
        gpu_count=1,
        required_gpu_free_memory_bytes=8 * 1024**3,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )
    scheduler.allocate("exclusive", _scope(), exclusive)
    try:
        scheduler.allocate("shared", _scope(), shared)
    except RuntimeError as exc:
        assert "no compute host" in str(exc)
    else:
        raise AssertionError(
            "shared work violated an existing idle-only GPU allocation"
        )


def test_fractional_gpu_memory_requirement_uses_live_residual_capacity() -> None:
    requirement = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=4 * 1024**3,
        gpu_count=1,
        minimum_gpu_memory_bytes=40 * 1024**3,
        required_gpu_memory_fraction=0.75,
        max_gpu_utilization_percent=100,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )
    scheduler = compute_scheduler(
        _inventory(),
        gpu_runtime_observer=_Observer(
            _snapshot(idle_free=70 * 1024, busy_free=48 * 1024)
        ),
    )

    allocation = scheduler.allocate("fractional", _scope(), requirement)

    assert allocation.gpu_ids == ("GPU-idle",)


def test_fractional_gpu_memory_requirement_rejects_when_no_gpu_has_enough_free_vram() -> None:
    requirement = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=4 * 1024**3,
        gpu_count=1,
        minimum_gpu_memory_bytes=40 * 1024**3,
        required_gpu_memory_fraction=0.75,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )
    scheduler = compute_scheduler(
        _inventory(),
        gpu_runtime_observer=_Observer(
            _snapshot(idle_free=55 * 1024, busy_free=48 * 1024)
        ),
    )

    try:
        scheduler.allocate("fractional-exhausted", _scope(), requirement)
    except RuntimeError as exc:
        assert "no compute host" in str(exc)
    else:
        raise AssertionError("fractional VRAM demand was admitted without residual capacity")


def test_fractional_vram_uses_larger_live_total_when_inventory_is_stale() -> None:
    requirement = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=4 * 1024**3,
        gpu_count=1,
        required_gpu_memory_fraction=0.75,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )
    scheduler = compute_scheduler(
        _inventory(),
        gpu_runtime_observer=_Observer(
            _snapshot(
                idle_total=96 * 1024,
                idle_free=70 * 1024,
                busy_total=96 * 1024,
                busy_free=48 * 1024,
            )
        ),
    )

    try:
        scheduler.allocate("live-total-drift", _scope(), requirement)
    except RuntimeError as exc:
        assert "no compute host" in str(exc)
    else:
        raise AssertionError(
            "fractional VRAM demand trusted stale smaller inventory capacity"
        )


def test_scheduler_rejects_unresolved_shared_gpu_memory_demand() -> None:
    requirement = ComputeRequirement(
        cpu_cores=1,
        memory_bytes=1,
        gpu_count=1,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )
    scheduler = compute_scheduler(
        _inventory(),
        gpu_runtime_observer=_Observer(_snapshot()),
    )

    try:
        scheduler.allocate("unresolved-shared", _scope(), requirement)
    except ValueError as exc:
        assert "shared GPU scheduling requires" in str(exc)
    else:
        raise AssertionError("scheduler admitted shared GPU work with no VRAM demand")


def test_shared_gpu_mode_accepts_fraction_as_its_memory_reservation() -> None:
    requirement = ComputeRequirement(
        cpu_cores=1,
        memory_bytes=1,
        gpu_count=1,
        required_gpu_memory_fraction=0.5,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )
    assert requirement.required_gpu_free_memory_bytes == 0
    assert requirement.required_gpu_memory_fraction == 0.5


def test_runtime_scheduler_rejects_shared_gpu_above_utilization_ceiling() -> None:
    scheduler = compute_scheduler(
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
    scheduler = ComputeScheduler(
        tmp_path / "compute.sqlite",
        _inventory(),
        clock=ManualLeaseClock(
            elapsed_seconds=1.0,
            wall_epoch_seconds=100.0,
        ),
        gpu_runtime_observer=_Observer(_snapshot()),
    )
    first = scheduler.allocate("first", _scope(), _requirement())
    assert first.gpu_ids == ("GPU-idle",)
    second = scheduler.allocate("second", _scope(), _requirement())
    # The live observer still reports 70 GiB free on GPU-idle. The first
    # unbound Noetrium reservation subtracts 24 GiB, leaving 46 GiB, so packing
    # another 24 GiB reservation there is both safe and preferred over an
    # externally busy GPU.
    assert second.gpu_ids == ("GPU-idle",)


class _UnavailableObserver:
    def snapshot(self) -> GpuRuntimeSnapshot:
        return GpuRuntimeSnapshot(False, detail="nvidia-smi unavailable")


class _FailingObserver:
    def snapshot(self) -> GpuRuntimeSnapshot:
        raise RuntimeError("observer failed")


def test_shared_gpu_mode_fails_closed_without_live_runtime_facts() -> None:
    for observer in (_UnavailableObserver(), _FailingObserver()):
        scheduler = compute_scheduler(_inventory(), gpu_runtime_observer=observer)
        try:
            scheduler.allocate("unknown", _scope(), _requirement())
        except RuntimeError as exc:
            assert "no compute host" in str(exc)
        else:
            raise AssertionError("shared GPU allocation admitted without live usage facts")


def test_idle_only_gpu_mode_fails_closed_without_runtime_observation() -> None:
    strict = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=4 * 1024**3,
        gpu_count=1,
        minimum_gpu_memory_bytes=40 * 1024**3,
        gpu_sharing_mode=GpuSharingMode.IDLE_ONLY,
    )
    for observer in (None, _UnavailableObserver(), _FailingObserver()):
        kwargs = {} if observer is None else {"gpu_runtime_observer": observer}
        scheduler = compute_scheduler(_inventory(), **kwargs)
        try:
            scheduler.allocate("strict-no-runtime", _scope(), strict)
        except RuntimeError as exc:
            assert "no compute host" in str(exc)
        else:
            raise AssertionError(
                "idle-only GPU allocation admitted without runtime observation"
            )


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
    scheduler = compute_scheduler(
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
    strict_scheduler = compute_scheduler(
        _inventory(), gpu_runtime_observer=_IncompleteProcessObserver()
    )
    try:
        strict_scheduler.allocate("strict-unknown", _scope(), strict)
    except RuntimeError as exc:
        assert "no compute host" in str(exc)
    else:
        raise AssertionError("idle-only scheduling trusted incomplete process visibility")


def test_unbound_placement_revalidation_uses_live_free_memory_without_double_counting_self() -> None:
    observer = _Observer(_single_gpu_snapshot(free_gib=30))
    scheduler = compute_scheduler(
        _single_gpu_inventory(),
        gpu_runtime_observer=observer,
    )
    requirement = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=4 * 1024**3,
        gpu_count=1,
        required_gpu_free_memory_bytes=24 * 1024**3,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )
    allocation = scheduler.allocate("revalidate-self", _scope(), requirement)

    # Its own 24 GiB reservation must not be subtracted again during exact
    # revalidation; the physical 30 GiB free still satisfies the placement.
    assert scheduler.unbound_placement_satisfies(allocation, requirement)

    # External usage arriving after admission is visible immediately and makes
    # the exact still-unbound placement invalid.
    observer.value = _single_gpu_snapshot(free_gib=20)
    assert not scheduler.unbound_placement_satisfies(allocation, requirement)
