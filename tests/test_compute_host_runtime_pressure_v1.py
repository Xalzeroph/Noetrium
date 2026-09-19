from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeHost,
    ComputeRequirement,
    HostRuntimeSnapshot,
    HostRuntimeStatus,
)
from noetrium_platform.infrastructure.resources.compute.runtime import (
    InMemoryComputeInventory,
    SQLiteComputeScheduler,
)
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


def test_sqlite_scheduler_applies_same_live_pressure_policy(tmp_path) -> None:
    scheduler = SQLiteComputeScheduler(
        tmp_path / "compute.sqlite", _inventory(),
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
