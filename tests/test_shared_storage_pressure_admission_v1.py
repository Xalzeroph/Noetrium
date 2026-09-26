from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from noetrium_platform.composition.shared_host_pressure import (
    LocalSharedStoragePressureObserver,
    ResourceCompetitionAdmissionGate,
    ResourceCompetitionDemand,
    ResourceCompetitionPolicy,
    SharedStoragePressureStatus,
    StorageCompetitionDemand,
)
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionLaneKind
from noetrium_platform.infrastructure.resources.compute.api import (
    HostRuntimeSnapshot,
    HostRuntimeStatus,
)
from noetrium_platform.infrastructure.resources.directory.api import (
    ManagedDirectoryKind,
)
from noetrium_platform.infrastructure.resources.directory.runtime import (
    build_local_directory_authorities,
    standard_local_directory_layout,
)
from noetrium_platform.research.execution.policy.api import (
    AdmissionBudget,
    AdmissionIdentity,
    AdmissionIntent,
    AdmissionRejected,
)
from noetrium_platform.research.execution.policy.composition import (
    build_admission_scheduling_policy,
    build_execution_admission,
)


class _HostObserver:
    def snapshot(self) -> HostRuntimeSnapshot:
        return HostRuntimeSnapshot(
            True,
            (
                HostRuntimeStatus(
                    "shared-node",
                    True,
                    effective_cpu_cores=8.0,
                    cpu_load_1m=0.0,
                    available_memory_bytes=32 * 1024**3,
                    cpu_pressure_some_avg10_percent=0.0,
                    memory_pressure_some_avg10_percent=0.0,
                    io_pressure_some_avg10_percent=0.0,
                    available_pids=1024,
                    available_fds=4096,
                ),
            ),
        )


class _StorageObserver:
    def __init__(self, status: SharedStoragePressureStatus) -> None:
        self.status = status

    def snapshot(self, path=None) -> SharedStoragePressureStatus:
        del path
        return self.status


def _gate(
    storage: _StorageObserver,
    *,
    min_storage_free_fraction: float = 0.0,
) -> ResourceCompetitionAdmissionGate:
    base = build_execution_admission(
        budget=AdmissionBudget(max_total_in_flight=8),
        scheduling=build_admission_scheduling_policy(priority_aging_seconds=0.01),
    )
    gate = ResourceCompetitionAdmissionGate(
        base,
        _HostObserver(),
        storage_observer=storage,
        policy=ResourceCompetitionPolicy(
            min_available_memory_bytes=0,
            min_available_pids=0,
            min_storage_free_bytes=1024,
            min_storage_free_inodes=10,
            min_storage_free_fraction=min_storage_free_fraction,
        ),
    )
    gate.register_group(
        "work",
        identity=AdmissionIdentity(),
        intent=AdmissionIntent(queue_wait_timeout_seconds=0.0),
    )
    return gate


def _storage_demand(
    path: Path,
    *,
    bytes_per_permit: int = 0,
    inodes_per_permit: int = 0,
) -> ResourceCompetitionDemand:
    return ResourceCompetitionDemand(
        storage_targets=(
            StorageCompetitionDemand(
                path,
                bytes_per_permit=bytes_per_permit,
                inodes_per_permit=inodes_per_permit,
            ),
        ),
    )


def test_storage_byte_exhaustion_rejects_new_io_without_throttling_cpu() -> None:
    gate = _gate(_StorageObserver(SharedStoragePressureStatus(True, 512, 100, capacity_id="dev:managed")))

    cpu = gate.acquire(
        "work",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    cpu.release()
    gate.set_group_demand(
        "work",
        _storage_demand(Path("/managed-storage")),
    )

    with pytest.raises(AdmissionRejected, match="storage-byte-headroom"):
        gate.acquire(
            "work",
            ExecutionLaneKind.BLOCKING_IO,
            deadline=None,
            cancellation=None,
        )


def test_storage_inode_exhaustion_rejects_even_with_free_bytes() -> None:
    gate = _gate(_StorageObserver(SharedStoragePressureStatus(True, 4096, 3, capacity_id="dev:managed")))
    gate.set_group_demand(
        "work",
        _storage_demand(Path("/managed-storage")),
    )
    with pytest.raises(AdmissionRejected, match="storage-inode-headroom"):
        gate.acquire(
            "work",
            ExecutionLaneKind.BLOCKING_IO,
            deadline=None,
            cancellation=None,
        )


def test_unknown_inode_capacity_fails_closed_when_inode_headroom_is_required() -> None:
    gate = _gate(_StorageObserver(SharedStoragePressureStatus(True, 4096, None, capacity_id="dev:managed")))
    gate.set_group_demand(
        "work",
        _storage_demand(Path("/managed-storage")),
    )
    with pytest.raises(
        AdmissionRejected,
        match="storage-inode-runtime-unavailable",
    ):
        gate.acquire(
            "work",
            ExecutionLaneKind.BLOCKING_IO,
            deadline=None,
            cancellation=None,
        )


class _ScopedStorageObserver:
    def __init__(
        self,
        statuses: dict[str, SharedStoragePressureStatus],
    ) -> None:
        self.statuses = statuses

    def snapshot(self, path=None) -> SharedStoragePressureStatus:
        if path is None:
            rows = tuple(self.statuses.values())
            inode_values = tuple(
                row.free_inodes
                for row in rows
                if row.free_inodes is not None
            )
            return SharedStoragePressureStatus(
                True,
                min(row.free_bytes for row in rows),
                None if not inode_values else min(inode_values),
                capacity_id=None,
            )
        return self.statuses[str(path)]


def _scoped_gate(
    storage: _ScopedStorageObserver,
) -> ResourceCompetitionAdmissionGate:
    base = build_execution_admission(
        budget=AdmissionBudget(max_total_in_flight=8),
        scheduling=build_admission_scheduling_policy(
            priority_aging_seconds=0.01
        ),
    )
    return ResourceCompetitionAdmissionGate(
        base,
        _HostObserver(),
        storage_observer=storage,
        policy=ResourceCompetitionPolicy(
            min_available_memory_bytes=0,
            min_available_pids=0,
            min_available_fds=0,
            min_storage_free_bytes=1024,
            min_storage_free_inodes=10,
            min_storage_free_fraction=0.0,
        ),
    )


def test_scoped_storage_pressure_does_not_freeze_unrelated_filesystem(
    tmp_path,
) -> None:
    left = (tmp_path / "left").absolute()
    right = (tmp_path / "right").absolute()
    storage = _ScopedStorageObserver(
        {
            str(left): SharedStoragePressureStatus(
                True,
                512,
                100,
                capacity_id="dev:left",
            ),
            str(right): SharedStoragePressureStatus(
                True,
                8192,
                100,
                capacity_id="dev:right",
            ),
        }
    )
    gate = _scoped_gate(storage)
    for group, path in (("left", left), ("right", right)):
        gate.register_group(
            group,
            identity=AdmissionIdentity(),
            intent=AdmissionIntent(queue_wait_timeout_seconds=0.0),
        )
        gate.set_group_demand(
            group,
            _storage_demand(path),
        )

    with pytest.raises(AdmissionRejected, match="storage-byte-headroom"):
        gate.acquire(
            "left",
            ExecutionLaneKind.BLOCKING_IO,
            deadline=None,
            cancellation=None,
        )

    lease = gate.acquire(
        "right",
        ExecutionLaneKind.BLOCKING_IO,
        deadline=None,
        cancellation=None,
    )
    lease.release()


def test_scoped_storage_reservations_compete_only_on_same_filesystem(
    tmp_path,
) -> None:
    left = (tmp_path / "left").absolute()
    right = (tmp_path / "right").absolute()
    storage = _ScopedStorageObserver(
        {
            str(left): SharedStoragePressureStatus(
                True,
                4096,
                100,
                capacity_id="dev:left",
            ),
            str(right): SharedStoragePressureStatus(
                True,
                4096,
                100,
                capacity_id="dev:right",
            ),
        }
    )
    gate = _scoped_gate(storage)
    for group, path in (
        ("left-a", left),
        ("left-b", left),
        ("right", right),
    ):
        gate.register_group(
            group,
            identity=AdmissionIdentity(),
            intent=AdmissionIntent(queue_wait_timeout_seconds=0.0),
        )
        gate.set_group_demand(
            group,
            _storage_demand(
                path,
                bytes_per_permit=2048,
            ),
        )

    left_lease = gate.acquire(
        "left-a",
        ExecutionLaneKind.BLOCKING_IO,
        deadline=None,
        cancellation=None,
    )
    with pytest.raises(AdmissionRejected, match="storage-byte-headroom"):
        gate.acquire(
            "left-b",
            ExecutionLaneKind.BLOCKING_IO,
            deadline=None,
            cancellation=None,
        )

    right_lease = gate.acquire(
        "right",
        ExecutionLaneKind.BLOCKING_IO,
        deadline=None,
        cancellation=None,
    )
    right_lease.release()
    left_lease.release()


def test_explicit_storage_target_is_hard_gated_on_cpu_lane(tmp_path) -> None:
    target = (tmp_path / "cpu-storage").absolute()
    storage = _ScopedStorageObserver(
        {
            str(target): SharedStoragePressureStatus(
                True,
                512,
                100,
                capacity_id="dev:cpu-storage",
                total_bytes=8192,
            ),
        }
    )
    gate = _scoped_gate(storage)
    gate.register_group(
        "cpu-storage",
        identity=AdmissionIdentity(),
        intent=AdmissionIntent(queue_wait_timeout_seconds=0.0),
    )
    gate.set_group_demand(
        "cpu-storage",
        _storage_demand(target),
    )

    with pytest.raises(AdmissionRejected, match="storage-byte-headroom"):
        gate.acquire(
            "cpu-storage",
            ExecutionLaneKind.CPU,
            deadline=None,
            cancellation=None,
        )


def test_explicit_storage_target_enforces_fraction_watermark(tmp_path) -> None:
    target = (tmp_path / "fraction-storage").absolute()
    gate = _gate(
        _StorageObserver(
            SharedStoragePressureStatus(
                True,
                4_000,
                100,
                capacity_id="dev:fraction",
                total_bytes=100_000,
            )
        ),
        min_storage_free_fraction=0.05,
    )
    gate.set_group_demand(
        "work",
        _storage_demand(target),
    )

    with pytest.raises(AdmissionRejected, match="storage-fraction-headroom"):
        gate.acquire(
            "work",
            ExecutionLaneKind.CPU,
            deadline=None,
            cancellation=None,
        )


def test_storage_fraction_accounts_for_live_reservations() -> None:
    target = Path("/fraction-reservation")
    storage = _StorageObserver(
        SharedStoragePressureStatus(
            True,
            6_000,
            100,
            capacity_id="dev:fraction-reservation",
            total_bytes=100_000,
        )
    )
    gate = _gate(storage, min_storage_free_fraction=0.05)
    gate.register_group(
        "second",
        identity=AdmissionIdentity(),
        intent=AdmissionIntent(queue_wait_timeout_seconds=0.0),
    )
    demand = _storage_demand(target, bytes_per_permit=750)
    gate.set_group_demand("work", demand)
    gate.set_group_demand("second", demand)

    first = gate.acquire(
        "work",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    with pytest.raises(AdmissionRejected, match="storage-fraction-headroom"):
        gate.acquire(
            "second",
            ExecutionLaneKind.CPU,
            deadline=None,
            cancellation=None,
        )
    first.release()

    second = gate.acquire(
        "second",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    second.release()


def test_storage_capacity_recovery_reenables_aggressive_admission() -> None:
    storage = _StorageObserver(SharedStoragePressureStatus(True, 512, 100, capacity_id="dev:managed"))
    gate = _gate(storage)
    gate.set_group_demand(
        "work",
        _storage_demand(Path("/managed-storage")),
    )
    with pytest.raises(AdmissionRejected, match="storage-byte-headroom"):
        gate.acquire(
            "work",
            ExecutionLaneKind.CPU,
            deadline=None,
            cancellation=None,
        )

    storage.status = SharedStoragePressureStatus(True, 4096, 100, capacity_id="dev:managed")
    lease = gate.acquire(
        "work",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    lease.release()


def test_multi_storage_demand_fails_when_any_filesystem_is_below_headroom(
    tmp_path,
) -> None:
    workspace = (tmp_path / "workspace").absolute()
    docker = (tmp_path / "docker").absolute()
    storage = _ScopedStorageObserver(
        {
            str(workspace): SharedStoragePressureStatus(
                True,
                8192,
                100,
                capacity_id="dev:workspace",
                total_bytes=100_000,
            ),
            str(docker): SharedStoragePressureStatus(
                True,
                512,
                100,
                capacity_id="dev:docker",
                total_bytes=100_000,
            ),
        }
    )
    gate = _scoped_gate(storage)
    gate.register_group(
        "multi-storage",
        identity=AdmissionIdentity(),
        intent=AdmissionIntent(queue_wait_timeout_seconds=0.0),
    )
    gate.set_group_demand(
        "multi-storage",
        ResourceCompetitionDemand(
            storage_targets=(
                StorageCompetitionDemand(workspace),
                StorageCompetitionDemand(docker),
            )
        ),
    )

    with pytest.raises(AdmissionRejected, match="storage-byte-headroom"):
        gate.acquire(
            "multi-storage",
            ExecutionLaneKind.CPU,
            deadline=None,
            cancellation=None,
        )


def test_paths_on_same_filesystem_share_one_storage_reservation(tmp_path) -> None:
    left = (tmp_path / "left-same-fs").absolute()
    right = (tmp_path / "right-same-fs").absolute()
    storage = _ScopedStorageObserver(
        {
            str(left): SharedStoragePressureStatus(
                True,
                5000,
                100,
                capacity_id="dev:shared",
                total_bytes=100_000,
            ),
            str(right): SharedStoragePressureStatus(
                True,
                5000,
                100,
                capacity_id="dev:shared",
                total_bytes=100_000,
            ),
        }
    )
    gate = _scoped_gate(storage)
    gate.register_group(
        "multi-path",
        identity=AdmissionIdentity(),
        intent=AdmissionIntent(queue_wait_timeout_seconds=0.0),
    )
    gate.register_group(
        "competitor",
        identity=AdmissionIdentity(),
        intent=AdmissionIntent(queue_wait_timeout_seconds=0.0),
    )
    gate.set_group_demand(
        "multi-path",
        ResourceCompetitionDemand(
            storage_targets=(
                StorageCompetitionDemand(left, bytes_per_permit=1500),
                StorageCompetitionDemand(right, bytes_per_permit=1500),
            )
        ),
    )
    gate.set_group_demand(
        "competitor",
        _storage_demand(left, bytes_per_permit=1500),
    )

    first = gate.acquire(
        "multi-path",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    with pytest.raises(AdmissionRejected, match="storage-byte-headroom"):
        gate.acquire(
            "competitor",
            ExecutionLaneKind.CPU,
            deadline=None,
            cancellation=None,
        )
    first.release()

    second = gate.acquire(
        "competitor",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    second.release()


def test_directory_usage_exposes_user_available_inode_headroom(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = standard_local_directory_layout(tmp_path)
    authorities = build_local_directory_authorities(layout)

    fake = SimpleNamespace(
        f_blocks=1000,
        f_bfree=500,
        f_bavail=400,
        f_frsize=4096,
        f_files=1000,
        f_favail=123,
    )
    monkeypatch.setattr(
        "noetrium_platform.infrastructure.resources.directory.runtime.inspection.os.statvfs",
        lambda _path: fake,
    )

    usage = authorities.inspection.usage(ManagedDirectoryKind.STATE)
    overview = authorities.inspection.overview(ManagedDirectoryKind.STATE)
    assert usage.total_inodes == 1000
    assert usage.free_inodes == 123
    assert overview.total_inodes == 1000
    assert overview.free_inodes == 123


def test_local_storage_observer_deduplicates_shared_filesystems(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    observer = LocalSharedStoragePressureObserver((left, right))

    stat = SimpleNamespace(
        f_blocks=100,
        f_bavail=50,
        f_frsize=4096,
        f_files=1000,
        f_favail=200,
    )
    monkeypatch.setattr(
        "noetrium_platform.composition.shared_host_pressure.os.statvfs",
        lambda _path: stat,
    )

    status = observer.snapshot()
    assert status.available
    assert status.free_bytes == 50 * 4096
    assert status.free_inodes == 200
