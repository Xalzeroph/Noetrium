from __future__ import annotations

from types import SimpleNamespace

import pytest

from noetrium_platform.composition.shared_host_pressure import (
    LocalSharedStoragePressureObserver,
    ResourceCompetitionAdmissionGate,
    ResourceCompetitionDemand,
    ResourceCompetitionPolicy,
    SharedStoragePressureStatus,
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


def _gate(storage: _StorageObserver) -> ResourceCompetitionAdmissionGate:
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
        ),
    )
    gate.register_group(
        "work",
        identity=AdmissionIdentity(),
        intent=AdmissionIntent(queue_wait_timeout_seconds=0.0),
    )
    return gate


def test_storage_byte_exhaustion_rejects_new_io_without_throttling_cpu() -> None:
    gate = _gate(_StorageObserver(SharedStoragePressureStatus(True, 512, 100)))

    cpu = gate.acquire(
        "work",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    cpu.release()

    with pytest.raises(AdmissionRejected, match="storage-byte-headroom"):
        gate.acquire(
            "work",
            ExecutionLaneKind.BLOCKING_IO,
            deadline=None,
            cancellation=None,
        )


def test_storage_inode_exhaustion_rejects_even_with_free_bytes() -> None:
    gate = _gate(_StorageObserver(SharedStoragePressureStatus(True, 4096, 3)))
    with pytest.raises(AdmissionRejected, match="storage-inode-headroom"):
        gate.acquire(
            "work",
            ExecutionLaneKind.BLOCKING_IO,
            deadline=None,
            cancellation=None,
        )


def test_unknown_inode_capacity_fails_closed_when_inode_headroom_is_required() -> None:
    gate = _gate(_StorageObserver(SharedStoragePressureStatus(True, 4096, None)))
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
            ResourceCompetitionDemand(storage_path=path),
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
            ResourceCompetitionDemand(
                storage_bytes_per_permit=2048,
                storage_path=path,
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


def test_storage_capacity_recovery_reenables_aggressive_admission() -> None:
    storage = _StorageObserver(SharedStoragePressureStatus(True, 4096, 100))
    gate = _gate(storage)
    lease = gate.acquire(
        "work",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    lease.release()


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
