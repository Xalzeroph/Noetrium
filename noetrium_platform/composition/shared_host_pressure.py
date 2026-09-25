from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import time
from typing import Protocol

from noetrium_platform.foundation.kernel.concurrency.api import (
    CancellationTokenPort,
    Deadline,
    ExecutionLaneKind,
    ExecutionPermitLeasePort,
    TaskCancelled,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    HostRuntimeObserverPort,
    HostRuntimeStatus,
)
from noetrium_platform.research.execution.policy.api import (
    AdmissionIdentity,
    AdmissionIntent,
    AdmissionMode,
    AdmissionRejected,
    AdmissionTopologySnapshot,
    ExecutionAdmissionPort,
    ExecutionPriority,
)


def configure_opportunistic_cpu_worker() -> None:
    """Make one CPU worker yield under host contention without capping idle use."""

    if os.name != "posix":
        return
    try:
        current = os.getpriority(os.PRIO_PROCESS, 0)
        if current < 5:
            os.setpriority(os.PRIO_PROCESS, 0, 5)
    except (AttributeError, OSError):
        pass
    oom_path = Path("/proc/self/oom_score_adj")
    try:
        current_oom = int(oom_path.read_text("utf-8").strip())
        if current_oom < 500:
            oom_path.write_text("500", encoding="utf-8")
    except (OSError, ValueError):
        pass


@dataclass(frozen=True, slots=True)
class SharedStoragePressureStatus:
    available: bool
    free_bytes: int = 0
    free_inodes: int | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if type(self.available) is not bool:
            raise TypeError("shared storage availability must be boolean")
        if type(self.free_bytes) is not int or self.free_bytes < 0:
            raise ValueError("shared storage free_bytes must be non-negative")
        if self.free_inodes is not None and (
            type(self.free_inodes) is not int or self.free_inodes < 0
        ):
            raise ValueError("shared storage free_inodes must be non-negative or None")


class SharedStoragePressureObserverPort(Protocol):
    def snapshot(self) -> SharedStoragePressureStatus: ...


class LocalSharedStoragePressureObserver:
    """Observe residual capacity across unique filesystems backing managed roots."""

    def __init__(self, paths: tuple[Path, ...]) -> None:
        if not paths or any(not isinstance(path, Path) for path in paths):
            raise ValueError("shared storage observer requires managed Path roots")
        self._paths = paths

    @staticmethod
    def _existing_capacity_path(path: Path) -> Path | None:
        current = path
        while True:
            if current.exists():
                return current
            parent = current.parent
            if parent == current:
                return None
            current = parent

    def snapshot(self) -> SharedStoragePressureStatus:
        by_device: dict[int, tuple[int, int | None]] = {}
        try:
            for requested in self._paths:
                path = self._existing_capacity_path(requested)
                if path is None:
                    return SharedStoragePressureStatus(
                        False,
                        detail=f"managed-storage-path-unresolvable:{requested}",
                    )
                device = int(path.stat().st_dev)
                if device in by_device:
                    continue
                stat = os.statvfs(path)
                free_bytes = max(0, int(stat.f_bavail) * int(stat.f_frsize))
                free_inodes = (
                    None
                    if int(stat.f_files) <= 0
                    else max(0, int(stat.f_favail))
                )
                by_device[device] = (free_bytes, free_inodes)
        except OSError as exc:
            return SharedStoragePressureStatus(
                False,
                detail=f"{type(exc).__name__}:{exc}",
            )
        if not by_device:
            return SharedStoragePressureStatus(False, detail="no-managed-filesystem")
        free_bytes = min(row[0] for row in by_device.values())
        inode_values = tuple(
            row[1] for row in by_device.values() if row[1] is not None
        )
        return SharedStoragePressureStatus(
            True,
            free_bytes=free_bytes,
            free_inodes=None if not inode_values else min(inode_values),
        )


@dataclass(frozen=True, slots=True)
class SharedHostPressurePolicy:
    """Aggressive residual-capacity policy for shared multi-user hosts.

    The policy never signals, kills, renices, deletes, or otherwise mutates
    external work. It only stops Noetrium from admitting additional workload
    while live host pressure says that doing so would consume capacity already
    needed by existing processes. CRITICAL control/recovery groups bypass this
    workload gate so fencing, lease renewal, checkpointing, and teardown cannot
    be starved by the pressure mechanism itself.
    """

    min_available_memory_bytes: int = 512 * 1024 * 1024
    min_available_pids: int = 32
    min_storage_free_bytes: int = 1024 * 1024 * 1024
    min_storage_free_inodes: int = 1024
    max_cpu_pressure_some_avg10_percent: float = 95.0
    max_memory_pressure_some_avg10_percent: float = 10.0
    max_io_pressure_some_avg10_percent: float = 50.0
    poll_interval_seconds: float = 0.05
    fail_closed_when_runtime_unavailable: bool = True

    def __post_init__(self) -> None:
        if type(self.min_available_memory_bytes) is not int or self.min_available_memory_bytes < 0:
            raise ValueError("shared-host memory headroom must be non-negative")
        if type(self.min_available_pids) is not int or self.min_available_pids < 0:
            raise ValueError("shared-host PID headroom must be non-negative")
        if type(self.min_storage_free_bytes) is not int or self.min_storage_free_bytes < 0:
            raise ValueError("shared-host storage byte headroom must be non-negative")
        if type(self.min_storage_free_inodes) is not int or self.min_storage_free_inodes < 0:
            raise ValueError("shared-host storage inode headroom must be non-negative")
        for name, value in (
            ("max_cpu_pressure_some_avg10_percent", self.max_cpu_pressure_some_avg10_percent),
            ("max_memory_pressure_some_avg10_percent", self.max_memory_pressure_some_avg10_percent),
            ("max_io_pressure_some_avg10_percent", self.max_io_pressure_some_avg10_percent),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0.0 <= float(value) <= 100.0
            ):
                raise ValueError(f"{name} must be a finite percentage")
        if (
            isinstance(self.poll_interval_seconds, bool)
            or not isinstance(self.poll_interval_seconds, (int, float))
            or not math.isfinite(float(self.poll_interval_seconds))
            or self.poll_interval_seconds <= 0
        ):
            raise ValueError("shared-host pressure poll interval must be finite and positive")
        if type(self.fail_closed_when_runtime_unavailable) is not bool:
            raise TypeError("shared-host runtime availability policy must be boolean")


class SharedHostPressureAdmissionGate(ExecutionAdmissionPort):
    """Composition gate that overlays external host pressure on normal admission."""

    def __init__(
        self,
        delegate: ExecutionAdmissionPort,
        observer: HostRuntimeObserverPort,
        *,
        storage_observer: SharedStoragePressureObserverPort | None = None,
        policy: SharedHostPressurePolicy = SharedHostPressurePolicy(),
    ) -> None:
        self._delegate = delegate
        self._observer = observer
        self._storage_observer = storage_observer
        self._policy = policy
        self._intents: dict[str, AdmissionIntent] = {}

    def register_group(
        self,
        group_id: str,
        *,
        identity: AdmissionIdentity,
        intent: AdmissionIntent = AdmissionIntent(),
    ) -> None:
        self._delegate.register_group(group_id, identity=identity, intent=intent)
        self._intents[group_id] = intent

    def unregister_group(self, group_id: str) -> None:
        self._delegate.unregister_group(group_id)
        self._intents.pop(group_id, None)

    def _status(self) -> HostRuntimeStatus | None:
        try:
            snapshot = self._observer.snapshot()
        except Exception:
            return None
        if not snapshot.available:
            return None
        rows = tuple(row for row in snapshot.hosts if row.available)
        return rows[0] if rows else None

    def _storage_status(self) -> SharedStoragePressureStatus | None:
        if self._storage_observer is None:
            return None
        try:
            status = self._storage_observer.snapshot()
        except Exception:
            return SharedStoragePressureStatus(False, detail="storage-observer-failed")
        return status

    def _pressure_reason(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        permit_count: int,
    ) -> str | None:
        intent = self._intents.get(group_id)
        if intent is None:
            raise KeyError(f"execution group is not registered with pressure gate: {group_id}")
        if intent.priority is ExecutionPriority.CRITICAL:
            return None

        status = self._status()
        if status is None:
            return (
                "host-runtime-unavailable"
                if self._policy.fail_closed_when_runtime_unavailable
                else None
            )

        if status.available_memory_bytes < self._policy.min_available_memory_bytes:
            return "memory-headroom"
        if (
            status.available_pids is not None
            and status.available_pids < self._policy.min_available_pids + permit_count
        ):
            return "pid-headroom"
        if (
            status.memory_pressure_some_avg10_percent is not None
            and status.memory_pressure_some_avg10_percent
            > self._policy.max_memory_pressure_some_avg10_percent
        ):
            return "memory-pressure"

        storage = self._storage_status()
        if self._storage_observer is not None:
            if storage is None or not storage.available:
                if self._policy.fail_closed_when_runtime_unavailable:
                    return "storage-runtime-unavailable"
            else:
                if storage.free_bytes < self._policy.min_storage_free_bytes:
                    return "storage-byte-headroom"
                if (
                    storage.free_inodes is not None
                    and storage.free_inodes < self._policy.min_storage_free_inodes
                ):
                    return "storage-inode-headroom"

        if lane_kind is ExecutionLaneKind.CPU:
            if status.effective_cpu_cores <= 0:
                return "cpu-capacity"
            if status.cpu_load_1m + permit_count > status.effective_cpu_cores:
                return "cpu-residual-capacity"
            if (
                status.cpu_pressure_some_avg10_percent is not None
                and status.cpu_pressure_some_avg10_percent
                > self._policy.max_cpu_pressure_some_avg10_percent
            ):
                return "cpu-pressure"

        if lane_kind in {ExecutionLaneKind.BLOCKING_IO, ExecutionLaneKind.ASYNC_IO}:
            if (
                status.io_pressure_some_avg10_percent is not None
                and status.io_pressure_some_avg10_percent
                > self._policy.max_io_pressure_some_avg10_percent
            ):
                return "io-pressure"

        return None

    @staticmethod
    def _cancelled(cancellation: CancellationTokenPort | None) -> bool:
        return cancellation is not None and cancellation.cancelled

    def _wait_for_pressure_clearance(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        permit_count: int,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> None:
        intent = self._intents.get(group_id)
        if intent is None:
            raise KeyError(f"execution group is not registered with pressure gate: {group_id}")
        while True:
            reason = self._pressure_reason(group_id, lane_kind, permit_count)
            if reason is None:
                return
            if intent.mode is AdmissionMode.REJECT:
                raise AdmissionRejected(
                    "shared-host pressure rejected execution admission: "
                    f"group={group_id} lane={lane_kind.value} reason={reason}"
                )
            if self._cancelled(cancellation):
                raise TaskCancelled(
                    cancellation.reason or "shared-host pressure admission cancelled"
                )
            if deadline is not None and deadline.expired:
                raise TimeoutError(
                    "shared-host pressure admission deadline expired: "
                    f"group={group_id} lane={lane_kind.value} reason={reason}"
                )
            remaining = None if deadline is None else deadline.remaining_seconds
            sleep_for = (
                self._policy.poll_interval_seconds
                if remaining is None
                else min(self._policy.poll_interval_seconds, remaining)
            )
            if sleep_for <= 0:
                raise TimeoutError("shared-host pressure admission deadline expired")
            time.sleep(sleep_for)

    def acquire(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> ExecutionPermitLeasePort:
        leases = self.acquire_many(
            group_id,
            lane_kind,
            permit_count=1,
            deadline=deadline,
            cancellation=cancellation,
        )
        if len(leases) != 1:
            raise RuntimeError("shared-host pressure gate returned invalid lease cardinality")
        return leases[0]

    def acquire_many(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        permit_count: int,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> tuple[ExecutionPermitLeasePort, ...]:
        if type(permit_count) is not int or permit_count <= 0:
            raise ValueError("shared-host pressure permit_count must be positive")
        self._wait_for_pressure_clearance(
            group_id,
            lane_kind,
            permit_count=permit_count,
            deadline=deadline,
            cancellation=cancellation,
        )
        return self._delegate.acquire_many(
            group_id,
            lane_kind,
            permit_count=permit_count,
            deadline=deadline,
            cancellation=cancellation,
        )

    def snapshot(self) -> AdmissionTopologySnapshot:
        return self._delegate.snapshot()

    def close(self) -> None:
        self._delegate.close()


__all__ = [
    "LocalSharedStoragePressureObserver",
    "configure_opportunistic_cpu_worker",
    "SharedHostPressureAdmissionGate",
    "SharedHostPressurePolicy",
    "SharedStoragePressureObserverPort",
    "SharedStoragePressureStatus",
]
