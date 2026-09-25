import pytest

from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeBindingProof,
    ComputeHost,
    ComputePlacementUnavailable,
    ComputeRequirement,
    HostRuntimeSnapshot,
    HostRuntimeStatus,
)
from noetrium_platform.infrastructure.resources.compute.runtime import (
    InMemoryComputeInventory,
    SQLiteComputeScheduler,
)
from noetrium_platform.infrastructure.resources.lease.runtime import ManualLeaseClock
from tests.resource_compute_support import in_memory_compute_scheduler


class _HostObserver:
    def __init__(self, *statuses: HostRuntimeStatus) -> None:
        self._snapshot = HostRuntimeSnapshot(True, tuple(statuses))

    def snapshot(self) -> HostRuntimeSnapshot:
        return self._snapshot


def _scope() -> ScopeIdentity:
    return ScopeIdentity(ScopeKind.PROJECT, "runtime-pressure")


def _inventory() -> InMemoryComputeInventory:
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("node-a", _scope(), 16, 64 * 1024**3))
    inventory.register_host(ComputeHost("node-b", _scope(), 16, 64 * 1024**3))
    return inventory


def _status(host: str, *, load: float, memory_gib: int) -> HostRuntimeStatus:
    return HostRuntimeStatus(
        host, True, effective_cpu_cores=16.0, cpu_load_1m=load,
        available_memory_bytes=memory_gib * 1024**3,
    )


def test_runtime_required_fails_closed_without_host_observer() -> None:
    scheduler = in_memory_compute_scheduler(_inventory())
    requirement = ComputeRequirement(
        cpu_cores=2, memory_bytes=1024, require_host_runtime=True
    )
    try:
        scheduler.allocate("required", _scope(), requirement)
    except RuntimeError as exc:
        assert "no compute host" in str(exc)
    else:
        raise AssertionError("runtime-required work admitted without live host facts")


def test_scheduler_prefers_lower_external_pressure() -> None:
    scheduler = in_memory_compute_scheduler(
        _inventory(),
        host_runtime_observer=_HostObserver(
            _status("node-a", load=12.0, memory_gib=40),
            _status("node-b", load=2.0, memory_gib=40),
        ),
    )
    allocation = scheduler.allocate(
        "low-pressure", _scope(),
        ComputeRequirement(
            cpu_cores=2, memory_bytes=4 * 1024**3, require_host_runtime=True
        ),
    )
    assert allocation.host_id == "node-b"


def test_default_runtime_policy_keeps_competing_at_full_cpu_load() -> None:
    scheduler = in_memory_compute_scheduler(
        _inventory(),
        host_runtime_observer=_HostObserver(
            _status("node-a", load=16.0, memory_gib=40),
            _status("node-b", load=16.0, memory_gib=40),
        ),
    )
    allocation = scheduler.allocate(
        "aggressive-cpu",
        _scope(),
        ComputeRequirement(
            cpu_cores=8,
            memory_bytes=1024,
            require_host_runtime=True,
        ),
    )
    assert allocation.cpu_cores == 8


def test_explicit_cpu_load_ceiling_remains_enforceable() -> None:
    scheduler = in_memory_compute_scheduler(
        _inventory(),
        host_runtime_observer=_HostObserver(
            _status("node-a", load=12.0, memory_gib=40),
            _status("node-b", load=12.0, memory_gib=40),
        ),
    )
    requirement = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=1024,
        require_host_runtime=True,
        max_cpu_load_ratio=0.5,
    )
    assert scheduler.candidates(requirement, scope=_scope()) == ()


def test_explicit_cpu_headroom_remains_enforceable() -> None:
    scheduler = in_memory_compute_scheduler(
        _inventory(),
        host_runtime_observer=_HostObserver(
            _status("node-a", load=14.0, memory_gib=40),
            _status("node-b", load=14.0, memory_gib=40),
        ),
    )
    requirement = ComputeRequirement(
        cpu_cores=1,
        memory_bytes=1024,
        require_host_runtime=True,
        cpu_headroom_cores=2,
    )
    assert scheduler.candidates(requirement, scope=_scope()) == ()


def test_runtime_memory_headroom_blocks_unsafe_placement() -> None:
    scheduler = in_memory_compute_scheduler(
        _inventory(),
        host_runtime_observer=_HostObserver(
            _status("node-a", load=1.0, memory_gib=10),
            _status("node-b", load=1.0, memory_gib=10),
        ),
    )
    requirement = ComputeRequirement(
        cpu_cores=1,
        memory_bytes=8 * 1024**3,
        memory_headroom_bytes=4 * 1024**3,
        require_host_runtime=True,
    )
    assert scheduler.candidates(requirement, scope=_scope()) == ()


def test_runtime_pressure_and_committed_capacity_are_independent_constraints() -> None:
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("node-a", _scope(), 16, 64 * 1024**3))
    scheduler = in_memory_compute_scheduler(
        inventory,
        host_runtime_observer=_HostObserver(_status("node-a", load=4.0, memory_gib=60)),
    )
    scheduler.allocate(
        "existing", _scope(), ComputeRequirement(cpu_cores=4, memory_bytes=1024)
    )
    second = scheduler.allocate(
        "second", _scope(),
        ComputeRequirement(
            cpu_cores=10, memory_bytes=1024, require_host_runtime=True
        ),
    )
    assert second.cpu_cores == 10


def _fixed_residual_inventory() -> InMemoryComputeInventory:
    inventory = InMemoryComputeInventory()
    inventory.register_host(
        ComputeHost("node-a", _scope(), 32, 64 * 1024**3)
    )
    return inventory


def _fixed_residual_observer() -> _HostObserver:
    return _HostObserver(
        _status("node-a", load=1.0, memory_gib=10)
    )


def _bind(
    scheduler,
    allocation,
    *,
    binder: str = "a" * 64,
):
    return scheduler.confirm_bound(
        ComputeBindingProof(
            allocation_id=allocation.allocation_id,
            host_id=allocation.host_id,
            gpu_ids=allocation.gpu_ids,
            lease_fencing_token=allocation.lease_fencing_token,
            binder_identity_digest=binder,
            observed_at_epoch_s=101.0,
            evidence_ref="runtime-running",
        )
    )


def test_unmaterialized_compute_reservation_fences_stale_live_memory_snapshot() -> None:
    scheduler = in_memory_compute_scheduler(
        _fixed_residual_inventory(),
        host_runtime_observer=_fixed_residual_observer(),
    )
    requirement = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=6 * 1024**3,
        require_host_runtime=True,
    )
    first = scheduler.allocate("first", _scope(), requirement)
    assert not first.is_bound

    # The observer intentionally remains at 10 GiB to model the interval
    # before the first process is visible in host runtime facts.
    with pytest.raises(ComputePlacementUnavailable):
        scheduler.allocate("second", _scope(), requirement)

    bound = _bind(scheduler, first)
    assert bound.is_bound
    # Once exact physical ownership is attested, the same live snapshot is
    # authoritative for residual capacity and the reservation is not double
    # subtracted.
    second = scheduler.allocate("second", _scope(), requirement)
    assert second.memory_bytes == 6 * 1024**3


def test_sqlite_unmaterialized_reservation_survives_restart_and_fences_capacity(
    tmp_path,
) -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    database = tmp_path / "compute-binding.sqlite"
    requirement = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=6 * 1024**3,
        require_host_runtime=True,
    )
    first_scheduler = SQLiteComputeScheduler(
        database,
        _fixed_residual_inventory(),
        clock=clock,
        host_runtime_observer=_fixed_residual_observer(),
    )
    first = first_scheduler.allocate(
        "first",
        _scope(),
        requirement,
        ttl_seconds=60.0,
    )

    rebuilt = SQLiteComputeScheduler(
        database,
        _fixed_residual_inventory(),
        clock=clock,
        host_runtime_observer=_fixed_residual_observer(),
    )
    with pytest.raises(ComputePlacementUnavailable):
        rebuilt.allocate(
            "second",
            _scope(),
            requirement,
            ttl_seconds=60.0,
        )

    bound = _bind(rebuilt, first)
    assert bound.is_bound
    second = rebuilt.allocate(
        "second",
        _scope(),
        requirement,
        ttl_seconds=60.0,
    )
    assert second.memory_bytes == requirement.memory_bytes


def test_sqlite_scheduler_applies_same_live_pressure_policy(tmp_path) -> None:
    scheduler = SQLiteComputeScheduler(
        tmp_path / "compute.sqlite", _inventory(),
        clock=ManualLeaseClock(
            elapsed_seconds=1.0,
            wall_epoch_seconds=100.0,
        ),
        host_runtime_observer=_HostObserver(
            _status("node-a", load=15.0, memory_gib=50),
            _status("node-b", load=1.0, memory_gib=50),
        ),
    )
    allocation = scheduler.allocate(
        "sqlite-live", _scope(),
        ComputeRequirement(
            cpu_cores=2, memory_bytes=1024, require_host_runtime=True
        ),
    )
    assert allocation.host_id == "node-b"
