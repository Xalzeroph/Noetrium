from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import os
from pathlib import Path
from threading import Lock
import time
from typing import Callable, Protocol

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


@dataclass(frozen=True, slots=True)
class SharedNetworkPressureStatus:
    available: bool
    max_utilization_percent: float | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if type(self.available) is not bool:
            raise TypeError("shared network availability must be boolean")
        if self.max_utilization_percent is not None and (
            isinstance(self.max_utilization_percent, bool)
            or not isinstance(self.max_utilization_percent, (int, float))
            or not math.isfinite(float(self.max_utilization_percent))
            or not 0.0 <= float(self.max_utilization_percent) <= 100.0
        ):
            raise ValueError(
                "shared network utilization must be a finite percentage or None"
            )


class SharedNetworkPressureObserverPort(Protocol):
    def snapshot(self) -> SharedNetworkPressureStatus: ...


class LocalSharedNetworkPressureObserver:
    """Best-effort host/network-namespace link saturation observer."""

    def __init__(
        self,
        *,
        proc_net_dev: Path = Path("/proc/net/dev"),
        sys_class_net: Path = Path("/sys/class/net"),
        clock: Callable[[], float] = time.monotonic,
        minimum_sample_seconds: float = 0.05,
    ) -> None:
        if (
            isinstance(minimum_sample_seconds, bool)
            or not isinstance(minimum_sample_seconds, (int, float))
            or not math.isfinite(float(minimum_sample_seconds))
            or minimum_sample_seconds <= 0
        ):
            raise ValueError("network pressure sample interval must be finite and positive")
        self._proc_net_dev = proc_net_dev
        self._sys_class_net = sys_class_net
        self._clock = clock
        self._minimum_sample_seconds = float(minimum_sample_seconds)
        self._previous_at: float | None = None
        self._previous: dict[str, tuple[int, int, int]] = {}
        self._last = SharedNetworkPressureStatus(
            False,
            max_utilization_percent=None,
            detail="network-pressure-warming",
        )
        self._lock = Lock()

    def _read(self) -> dict[str, tuple[int, int, int]]:
        text = self._proc_net_dev.read_text("utf-8", errors="replace")
        rows: dict[str, tuple[int, int, int]] = {}
        for line in text.splitlines():
            if ":" not in line:
                continue
            name, raw = line.split(":", 1)
            interface = name.strip()
            if not interface or interface == "lo":
                continue
            fields = raw.split()
            if len(fields) < 16:
                continue
            try:
                rx_bytes = int(fields[0])
                tx_bytes = int(fields[8])
                speed_mbps = int(
                    (self._sys_class_net / interface / "speed")
                    .read_text("utf-8", errors="replace")
                    .strip()
                )
            except (OSError, ValueError):
                continue
            if rx_bytes < 0 or tx_bytes < 0 or speed_mbps <= 0:
                continue
            rows[interface] = (rx_bytes, tx_bytes, speed_mbps)
        return rows

    def snapshot(self) -> SharedNetworkPressureStatus:
        try:
            now = float(self._clock())
            if not math.isfinite(now):
                raise ValueError("network pressure clock is not finite")
            current = self._read()
        except (OSError, ValueError) as exc:
            return SharedNetworkPressureStatus(
                False,
                detail=f"{type(exc).__name__}:{exc}",
            )

        with self._lock:
            if not current:
                self._previous_at = now
                self._previous = {}
                self._last = SharedNetworkPressureStatus(
                    False,
                    max_utilization_percent=None,
                    detail="network-link-speed-unavailable",
                )
                return self._last

            if self._previous_at is None:
                self._previous_at = now
                self._previous = current
                return self._last

            elapsed = now - self._previous_at
            if elapsed < self._minimum_sample_seconds:
                return self._last

            percentages: list[float] = []
            for interface, (rx_bytes, tx_bytes, speed_mbps) in current.items():
                previous = self._previous.get(interface)
                if previous is None:
                    continue
                previous_rx, previous_tx, _previous_speed = previous
                capacity_bytes_per_second = speed_mbps * 1_000_000 / 8.0
                if capacity_bytes_per_second <= 0:
                    continue
                rx_rate = max(0, rx_bytes - previous_rx) / elapsed
                tx_rate = max(0, tx_bytes - previous_tx) / elapsed
                percentages.append(
                    min(
                        100.0,
                        100.0
                        * max(rx_rate, tx_rate)
                        / capacity_bytes_per_second,
                    )
                )

            self._previous_at = now
            self._previous = current
            self._last = SharedNetworkPressureStatus(
                bool(percentages),
                max_utilization_percent=(
                    None if not percentages else max(percentages)
                ),
                detail=(
                    "network-pressure-warming"
                    if not percentages
                    else ""
                ),
            )
            return self._last


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


class ResourceCompetitionClass(StrEnum):
    HARD_SAFETY = "hard-safety"
    SOFT_CONTENTION = "soft-contention"


@dataclass(frozen=True, slots=True)
class ResourceCompetitionDecision:
    admitted: bool
    reason: str | None = None
    competition_class: ResourceCompetitionClass | None = None

    def __post_init__(self) -> None:
        if type(self.admitted) is not bool:
            raise TypeError("resource competition decision admitted must be boolean")
        if self.admitted:
            if self.reason is not None or self.competition_class is not None:
                raise ValueError("admitted resource competition decision cannot carry a blocker")
            return
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("blocked resource competition decision requires a reason")
        if not isinstance(self.competition_class, ResourceCompetitionClass):
            raise TypeError("blocked resource competition decision requires a class")


_HARD_COMPETITION_REASONS = frozenset(
    {
        "host-runtime-unavailable",
        "memory-headroom",
        "pid-runtime-unavailable",
        "pid-headroom",
        "storage-runtime-unavailable",
        "storage-byte-headroom",
        "storage-inode-runtime-unavailable",
        "storage-inode-headroom",
        "cpu-capacity",
        "fd-runtime-unavailable",
        "fd-headroom",
    }
)

_SOFT_COMPETITION_REASONS = frozenset(
    {
        "memory-pressure-runtime-unavailable",
        "memory-pressure",
        "cpu-pressure-runtime-unavailable",
        "cpu-pressure",
        "network-runtime-unavailable",
        "network-pressure",
        "io-pressure-runtime-unavailable",
        "io-pressure",
    }
)


@dataclass(frozen=True, slots=True)
class ResourceCompetitionPolicy:
    """Hard-safety admission policy for shared multi-user hosts.

    Noetrium keeps competing when other users arrive. By default, CPU load,
    PSI, and link utilization are observation/evidence only; they do not make
    Noetrium yield. Admission stops only at explicit hard residual-capacity
    reserves such as memory, PID, FD, storage bytes, and storage inodes.
    Callers may opt into soft-pressure throttling by setting a threshold below
    100 percent. CRITICAL control/recovery groups always bypass this workload
    gate so fencing, lease renewal, checkpointing, and teardown cannot starve.
    External processes are never signalled, reniced, deleted, or otherwise
    mutated by this policy.
    """

    min_available_memory_bytes: int = 512 * 1024 * 1024
    min_available_pids: int = 32
    min_available_fds: int = 64
    min_storage_free_bytes: int = 1024 * 1024 * 1024
    min_storage_free_inodes: int = 1024
    max_cpu_pressure_some_avg10_percent: float = 100.0
    max_memory_pressure_some_avg10_percent: float = 100.0
    max_io_pressure_some_avg10_percent: float = 100.0
    max_network_utilization_percent: float = 100.0
    poll_interval_seconds: float = 0.05
    fail_closed_when_runtime_unavailable: bool = True

    def __post_init__(self) -> None:
        if type(self.min_available_memory_bytes) is not int or self.min_available_memory_bytes < 0:
            raise ValueError("shared-host memory headroom must be non-negative")
        if type(self.min_available_pids) is not int or self.min_available_pids < 0:
            raise ValueError("shared-host PID headroom must be non-negative")
        if type(self.min_available_fds) is not int or self.min_available_fds < 0:
            raise ValueError("shared-host FD headroom must be non-negative")
        if type(self.min_storage_free_bytes) is not int or self.min_storage_free_bytes < 0:
            raise ValueError("shared-host storage byte headroom must be non-negative")
        if type(self.min_storage_free_inodes) is not int or self.min_storage_free_inodes < 0:
            raise ValueError("shared-host storage inode headroom must be non-negative")
        for name, value in (
            ("max_cpu_pressure_some_avg10_percent", self.max_cpu_pressure_some_avg10_percent),
            ("max_memory_pressure_some_avg10_percent", self.max_memory_pressure_some_avg10_percent),
            ("max_io_pressure_some_avg10_percent", self.max_io_pressure_some_avg10_percent),
            ("max_network_utilization_percent", self.max_network_utilization_percent),
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


class ResourceCompetitionAdmissionGate(ExecutionAdmissionPort):
    """Composition gate that overlays external host pressure on normal admission."""

    def __init__(
        self,
        delegate: ExecutionAdmissionPort,
        observer: HostRuntimeObserverPort,
        *,
        storage_observer: SharedStoragePressureObserverPort | None = None,
        network_observer: SharedNetworkPressureObserverPort | None = None,
        policy: ResourceCompetitionPolicy = ResourceCompetitionPolicy(),
    ) -> None:
        self._delegate = delegate
        self._observer = observer
        self._storage_observer = storage_observer
        self._network_observer = network_observer
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

    def _network_status(self) -> SharedNetworkPressureStatus | None:
        if self._network_observer is None:
            return None
        try:
            status = self._network_observer.snapshot()
        except Exception:
            return SharedNetworkPressureStatus(False, detail="network-observer-failed")
        return status

    def _competition_reason(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        permit_count: int,
    ) -> str | None:
        intent = self._intents.get(group_id)
        if intent is None:
            raise KeyError(f"execution group is not registered with resource competition gate: {group_id}")
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
        if status.available_pids is None:
            if (
                self._policy.fail_closed_when_runtime_unavailable
                and self._policy.min_available_pids > 0
            ):
                return "pid-runtime-unavailable"
        elif status.available_pids < self._policy.min_available_pids + permit_count:
            return "pid-headroom"
        if status.memory_pressure_some_avg10_percent is None:
            if (
                self._policy.fail_closed_when_runtime_unavailable
                and self._policy.max_memory_pressure_some_avg10_percent < 100.0
            ):
                return "memory-pressure-runtime-unavailable"
        elif (
            status.memory_pressure_some_avg10_percent
            > self._policy.max_memory_pressure_some_avg10_percent
        ):
            return "memory-pressure"

        if lane_kind is ExecutionLaneKind.CPU:
            if status.effective_cpu_cores <= 0:
                return "cpu-capacity"
            if status.cpu_pressure_some_avg10_percent is None:
                if (
                    self._policy.fail_closed_when_runtime_unavailable
                    and self._policy.max_cpu_pressure_some_avg10_percent < 100.0
                ):
                    return "cpu-pressure-runtime-unavailable"
            elif (
                status.cpu_pressure_some_avg10_percent
                > self._policy.max_cpu_pressure_some_avg10_percent
            ):
                return "cpu-pressure"

        if lane_kind in {ExecutionLaneKind.BLOCKING_IO, ExecutionLaneKind.ASYNC_IO}:
            storage = self._storage_status()
            if self._storage_observer is not None:
                if storage is None or not storage.available:
                    if self._policy.fail_closed_when_runtime_unavailable:
                        return "storage-runtime-unavailable"
                else:
                    if storage.free_bytes < self._policy.min_storage_free_bytes:
                        return "storage-byte-headroom"
                    if storage.free_inodes is None:
                        if (
                            self._policy.fail_closed_when_runtime_unavailable
                            and self._policy.min_storage_free_inodes > 0
                        ):
                            return "storage-inode-runtime-unavailable"
                    elif storage.free_inodes < self._policy.min_storage_free_inodes:
                        return "storage-inode-headroom"
            if (
                self._network_observer is not None
                and self._policy.max_network_utilization_percent < 100.0
            ):
                network = self._network_status()
                if (
                    network is None
                    or not network.available
                    or network.max_utilization_percent is None
                ):
                    if self._policy.fail_closed_when_runtime_unavailable:
                        return "network-runtime-unavailable"
                elif (
                    network.max_utilization_percent
                    > self._policy.max_network_utilization_percent
                ):
                    return "network-pressure"
            if status.available_fds is None:
                if (
                    self._policy.fail_closed_when_runtime_unavailable
                    and self._policy.min_available_fds > 0
                ):
                    return "fd-runtime-unavailable"
            elif status.available_fds < self._policy.min_available_fds + permit_count:
                return "fd-headroom"
            if status.io_pressure_some_avg10_percent is None:
                if (
                    self._policy.fail_closed_when_runtime_unavailable
                    and self._policy.max_io_pressure_some_avg10_percent < 100.0
                ):
                    return "io-pressure-runtime-unavailable"
            elif (
                status.io_pressure_some_avg10_percent
                > self._policy.max_io_pressure_some_avg10_percent
            ):
                return "io-pressure"

        return None

    @staticmethod
    def _competition_class(reason: str) -> ResourceCompetitionClass:
        if reason in _HARD_COMPETITION_REASONS:
            return ResourceCompetitionClass.HARD_SAFETY
        if reason in _SOFT_COMPETITION_REASONS:
            return ResourceCompetitionClass.SOFT_CONTENTION
        raise RuntimeError(f"unclassified resource competition reason: {reason}")

    def decision(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        permit_count: int = 1,
    ) -> ResourceCompetitionDecision:
        if type(permit_count) is not int or permit_count <= 0:
            raise ValueError("resource competition permit_count must be positive")
        reason = self._competition_reason(group_id, lane_kind, permit_count)
        if reason is None:
            return ResourceCompetitionDecision(True)
        return ResourceCompetitionDecision(
            False,
            reason=reason,
            competition_class=self._competition_class(reason),
        )

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
            raise KeyError(f"execution group is not registered with resource competition gate: {group_id}")
        while True:
            decision = self.decision(group_id, lane_kind, permit_count=permit_count)
            reason = decision.reason
            if reason is None:
                return
            if intent.mode is AdmissionMode.REJECT:
                raise AdmissionRejected(
                    "resource competition rejected execution admission: "
                    f"group={group_id} lane={lane_kind.value} "
                    f"class={decision.competition_class.value} reason={reason}"
                )
            if self._cancelled(cancellation):
                raise TaskCancelled(
                    cancellation.reason or "resource competition admission cancelled"
                )
            if deadline is not None and deadline.expired:
                raise TimeoutError(
                    "resource competition admission deadline expired: "
                    f"group={group_id} lane={lane_kind.value} reason={reason}"
                )
            remaining = None if deadline is None else deadline.remaining_seconds
            sleep_for = (
                self._policy.poll_interval_seconds
                if remaining is None
                else min(self._policy.poll_interval_seconds, remaining)
            )
            if sleep_for <= 0:
                raise TimeoutError("resource competition admission deadline expired")
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
            raise RuntimeError("resource competition gate returned invalid lease cardinality")
        return leases[0]

    @staticmethod
    def _release_delegate_leases(
        leases: tuple[ExecutionPermitLeasePort, ...],
    ) -> None:
        errors: list[BaseException] = []
        for lease in reversed(leases):
            try:
                lease.release()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup(
                "resource competition failed to release provisional permits",
                errors,
            )

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
            raise ValueError("resource competition permit_count must be positive")
        intent = self._intents.get(group_id)
        if intent is None:
            raise KeyError(
                "execution group is not registered with resource competition gate: "
                f"{group_id}"
            )

        while True:
            self._wait_for_pressure_clearance(
                group_id,
                lane_kind,
                permit_count=permit_count,
                deadline=deadline,
                cancellation=cancellation,
            )
            leases = self._delegate.acquire_many(
                group_id,
                lane_kind,
                permit_count=permit_count,
                deadline=deadline,
                cancellation=cancellation,
            )
            if len(leases) != permit_count:
                self._release_delegate_leases(leases)
                raise RuntimeError(
                    "resource competition delegate returned invalid lease cardinality"
                )

            if self._cancelled(cancellation):
                self._release_delegate_leases(leases)
                raise TaskCancelled(
                    cancellation.reason or "resource competition admission cancelled"
                )
            if deadline is not None and deadline.expired:
                self._release_delegate_leases(leases)
                raise TimeoutError(
                    "resource competition admission deadline expired after provisional grant"
                )

            try:
                decision = self.decision(
                    group_id,
                    lane_kind,
                    permit_count=permit_count,
                )
            except BaseException:
                self._release_delegate_leases(leases)
                raise
            if decision.admitted:
                return leases

            self._release_delegate_leases(leases)
            if intent.mode is AdmissionMode.REJECT:
                raise AdmissionRejected(
                    "resource competition rejected execution admission after "
                    "provisional grant: "
                    f"group={group_id} lane={lane_kind.value} "
                    f"class={decision.competition_class.value} "
                    f"reason={decision.reason}"
                )
            # BLOCK mode loops through the pressure gate again. Existing
            # workload leases are never revoked; only this not-yet-returned
            # provisional grant is surrendered.

    def snapshot(self) -> AdmissionTopologySnapshot:
        return self._delegate.snapshot()

    def close(self) -> None:
        self._delegate.close()


__all__ = [
    "LocalSharedNetworkPressureObserver",
    "LocalSharedStoragePressureObserver",
    "ResourceCompetitionAdmissionGate",
    "ResourceCompetitionClass",
    "ResourceCompetitionDecision",
    "ResourceCompetitionPolicy",
    "SharedNetworkPressureObserverPort",
    "SharedNetworkPressureStatus",
    "SharedStoragePressureObserverPort",
    "SharedStoragePressureStatus",
]
