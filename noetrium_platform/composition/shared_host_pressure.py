from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import blocking_wait
from dataclasses import dataclass
from enum import StrEnum
import math
import os
from pathlib import Path
from threading import Lock, RLock, local
import time
from uuid import uuid4
from typing import Callable, Protocol

from noetrium_platform.foundation.kernel.kernel.canonical import (
    canonical_bytes,
    canonical_digest,
    strict_json_loads,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    atomic_replace_bytes,
)
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
    InterprocessLockBusy,
)
from noetrium_platform.foundation.kernel.kernel.lease_clock import LocalLeaseClock

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
from noetrium_platform.composition.runtime_coordination import (
    runtime_coordination_root,
    runtime_coordination_user_namespace,
)
from noetrium_platform.research.execution.policy.api import (
    AdmissionIdentity,
    AdmissionIntent,
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
    capacity_id: str | None = None
    total_bytes: int | None = None

    def __post_init__(self) -> None:
        if type(self.available) is not bool:
            raise TypeError("shared storage availability must be boolean")
        if type(self.free_bytes) is not int or self.free_bytes < 0:
            raise ValueError("shared storage free_bytes must be non-negative")
        if self.free_inodes is not None and (
            type(self.free_inodes) is not int or self.free_inodes < 0
        ):
            raise ValueError("shared storage free_inodes must be non-negative or None")
        if self.capacity_id is not None and (
            type(self.capacity_id) is not str or not self.capacity_id.strip()
        ):
            raise ValueError(
                "shared storage capacity_id must be non-empty text or None"
            )
        if self.total_bytes is not None:
            if type(self.total_bytes) is not int or self.total_bytes <= 0:
                raise ValueError(
                    "shared storage total_bytes must be positive or None"
                )
            if self.free_bytes > self.total_bytes:
                raise ValueError(
                    "shared storage free_bytes cannot exceed total_bytes"
                )


class SharedStoragePressureObserverPort(Protocol):
    def snapshot(
        self,
        path: Path | None = None,
    ) -> SharedStoragePressureStatus: ...


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

    @staticmethod
    def _capacity(
        requested: Path,
    ) -> SharedStoragePressureStatus:
        path = LocalSharedStoragePressureObserver._existing_capacity_path(
            requested
        )
        if path is None:
            return SharedStoragePressureStatus(
                False,
                detail=f"managed-storage-path-unresolvable:{requested}",
            )
        try:
            device = int(path.stat().st_dev)
            stat = os.statvfs(path)
        except OSError as exc:
            return SharedStoragePressureStatus(
                False,
                detail=f"{type(exc).__name__}:{exc}",
            )
        total_bytes = max(0, int(stat.f_blocks) * int(stat.f_frsize))
        free_bytes = max(0, int(stat.f_bavail) * int(stat.f_frsize))
        free_inodes = (
            None
            if int(stat.f_files) <= 0
            else max(0, int(stat.f_favail))
        )
        return SharedStoragePressureStatus(
            True,
            free_bytes=free_bytes,
            free_inodes=free_inodes,
            capacity_id=f"dev:{device}",
            total_bytes=(total_bytes if total_bytes > 0 else None),
        )

    def snapshot(
        self,
        path: Path | None = None,
    ) -> SharedStoragePressureStatus:
        if path is not None:
            if not isinstance(path, Path):
                raise TypeError("shared storage pressure path must be Path")
            return self._capacity(path)

        by_device: dict[str, SharedStoragePressureStatus] = {}
        for requested in self._paths:
            status = self._capacity(requested)
            if not status.available:
                return status
            assert status.capacity_id is not None
            by_device.setdefault(status.capacity_id, status)

        if not by_device:
            return SharedStoragePressureStatus(
                False,
                detail="no-managed-filesystem",
            )
        rows = tuple(by_device.values())
        inode_values = tuple(
            row.free_inodes
            for row in rows
            if row.free_inodes is not None
        )
        return SharedStoragePressureStatus(
            True,
            free_bytes=min(row.free_bytes for row in rows),
            free_inodes=(
                None if not inode_values else min(inode_values)
            ),
            capacity_id=(
                rows[0].capacity_id if len(rows) == 1 else None
            ),
            total_bytes=(
                rows[0].total_bytes if len(rows) == 1 else None
            ),
        )


@dataclass(frozen=True, slots=True)
class StorageCompetitionDemand:
    """Per-permit demand against one physical-storage lookup path."""

    path: Path
    bytes_per_permit: int = 0
    inodes_per_permit: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            raise TypeError("storage competition demand path must be Path")
        for name in ("bytes_per_permit", "inodes_per_permit"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(
                    f"storage competition demand {name} must be a non-negative integer"
                )
        object.__setattr__(self, "path", self.path.absolute())


@dataclass(frozen=True, slots=True)
class ResourceCompetitionDemand:
    """Physical residual-capacity increment associated with one admitted permit."""

    memory_bytes_per_permit: int = 0
    pids_per_permit: int = 0
    fds_per_permit: int = 0
    storage_targets: tuple[StorageCompetitionDemand, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "memory_bytes_per_permit",
            "pids_per_permit",
            "fds_per_permit",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(
                    f"resource competition demand {name} must be a non-negative integer"
                )
        if type(self.storage_targets) is not tuple:
            raise TypeError("resource competition storage_targets must be tuple")
        normalized: list[StorageCompetitionDemand] = []
        seen_paths: set[Path] = set()
        for target in self.storage_targets:
            if type(target) is not StorageCompetitionDemand:
                raise TypeError(
                    "resource competition storage target must be StorageCompetitionDemand"
                )
            if target.path in seen_paths:
                raise ValueError(
                    f"duplicate resource competition storage target: {target.path}"
                )
            seen_paths.add(target.path)
            normalized.append(target)
        normalized.sort(key=lambda row: str(row.path))
        object.__setattr__(self, "storage_targets", tuple(normalized))


@dataclass(frozen=True, slots=True)
class _ResolvedStorageCapacity:
    capacity_id: str
    status: SharedStoragePressureStatus
    bytes_per_permit: int
    inodes_per_permit: int


@dataclass(frozen=True, slots=True)
class _StorageReservation:
    capacity_id: str
    bytes_per_permit: int
    inodes_per_permit: int


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
        "storage-fraction-headroom",
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
    100 percent. CRITICAL zero-demand control/recovery groups bypass workload
    pressure so fencing, lease renewal, checkpointing, and teardown cannot starve.
    CRITICAL work that declares physical demand still obeys hard residual-capacity
    fences, while bypassing soft contention thresholds.
    External processes are never signalled, reniced, deleted, or otherwise
    mutated by this policy.
    """

    min_available_memory_bytes: int = 512 * 1024 * 1024
    min_available_pids: int = 32
    min_available_fds: int = 64
    min_storage_free_bytes: int = 1024 * 1024 * 1024
    min_storage_free_inodes: int = 1024
    min_storage_free_fraction: float = 0.03
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
        if (
            isinstance(self.min_storage_free_fraction, bool)
            or not isinstance(self.min_storage_free_fraction, (int, float))
            or not math.isfinite(float(self.min_storage_free_fraction))
            or not 0.0 <= float(self.min_storage_free_fraction) < 1.0
        ):
            raise ValueError(
                "shared-host storage free fraction must be finite in [0, 1)"
            )
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


class _ResourceCompetitionReservationLock:
    """Reusable local + interprocess transaction boundary for host reservations."""

    def __init__(self, ledger: "ResourceCompetitionReservationLedger") -> None:
        self._ledger = ledger

    def __enter__(self) -> "_ResourceCompetitionReservationLock":
        self._ledger._enter_transaction()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._ledger._exit_transaction(exc_type, exc, traceback)


def _default_resource_competition_directory() -> Path:
    reading = LocalLeaseClock().read()
    return (
        runtime_coordination_root()
        / "resource-competition"
        / runtime_coordination_user_namespace()
        / reading.host_identity_digest
        / reading.boot_identity_digest
    )


class ResourceCompetitionReservationLedger:
    """Host-scoped launch-window reservation authority.

    Live host facts lag process/thread/container launch. Admission therefore
    publishes logical capacity commitments before leaving the physical safety
    critical section. Commitments from every live Noetrium process in the same
    user/host/boot authority domain are aggregated.

    Each owner publishes canonical state while holding a unique kernel-backed
    owner lock. SIGKILL/process exit releases that lock automatically; the next
    admission transaction prunes the stale state before evaluating capacity.
    Foreign OS users are still accounted through live host facts, while this
    authority closes the same-user Noetrium launch visibility race.
    """

    _SCHEMA = "noetrium.resource-competition-reservation.v1"

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = (
            _default_resource_competition_directory()
            if directory is None
            else Path(directory).absolute()
        )
        self._directory.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            try:
                self._directory.chmod(0o700)
            except OSError:
                pass

        reading = LocalLeaseClock().read()
        self._host_identity_digest = reading.host_identity_digest
        self._boot_identity_digest = reading.boot_identity_digest
        self._owner_id = canonical_digest(
            {
                "schema": "noetrium.resource-competition-owner.v1",
                "pid": os.getpid(),
                "nonce": uuid4().hex,
                "host_identity_digest": self._host_identity_digest,
                "boot_identity_digest": self._boot_identity_digest,
            }
        )
        self._local_lock = RLock()
        self._thread_state = local()
        self._global_guard = InterprocessFileLock(
            self._directory / "reservation-authority.lock"
        )
        self._transaction_lock = _ResourceCompetitionReservationLock(self)
        self._owner_lock: InterprocessFileLock | None = None

        self._reserved_memory_bytes = 0
        self._reserved_pids = 0
        self._reserved_fds = 0
        self._reserved_storage_bytes: dict[str, int] = {}
        self._reserved_storage_inodes: dict[str, int] = {}

    @property
    def lock(self) -> _ResourceCompetitionReservationLock:
        return self._transaction_lock

    def _state_path(self, owner_id: str) -> Path:
        return self._directory / f"owner-{owner_id}.json"

    def _owner_lock_path(self, owner_id: str) -> Path:
        return self._directory / f"owner-{owner_id}.lock"

    def _enter_transaction(self) -> None:
        self._local_lock.acquire()
        depth = int(getattr(self._thread_state, "depth", 0))
        if depth:
            self._thread_state.depth = depth + 1
            return
        try:
            self._global_guard.__enter__()
            self._thread_state.depth = 1
            self._prune_stale_states_locked()
        except BaseException:
            self._thread_state.depth = 0
            try:
                self._global_guard.__exit__(None, None, None)
            except BaseException:
                pass
            self._local_lock.release()
            raise

    def _exit_transaction(self, exc_type, exc, traceback) -> None:
        depth = int(getattr(self._thread_state, "depth", 0))
        if depth <= 0:
            self._local_lock.release()
            raise RuntimeError("resource reservation transaction underflow")
        if depth > 1:
            self._thread_state.depth = depth - 1
            self._local_lock.release()
            return
        self._thread_state.depth = 0
        try:
            self._global_guard.__exit__(exc_type, exc, traceback)
        finally:
            self._local_lock.release()

    def _ensure_owner_lock_locked(self) -> None:
        if self._owner_lock is not None:
            return
        lock = InterprocessFileLock(self._owner_lock_path(self._owner_id))
        lock.__enter__()
        self._owner_lock = lock

    def _release_owner_lock_locked(self) -> None:
        lock = self._owner_lock
        if lock is None:
            return
        self._owner_lock = None
        lock.__exit__(None, None, None)

    def _local_is_zero_locked(self) -> bool:
        return (
            self._reserved_memory_bytes == 0
            and self._reserved_pids == 0
            and self._reserved_fds == 0
            and not self._reserved_storage_bytes
            and not self._reserved_storage_inodes
        )

    def _encode_local_state_locked(self) -> bytes:
        storage_ids = sorted(
            set(self._reserved_storage_bytes)
            | set(self._reserved_storage_inodes)
        )
        return canonical_bytes(
            {
                "schema": self._SCHEMA,
                "owner_id": self._owner_id,
                "host_identity_digest": self._host_identity_digest,
                "boot_identity_digest": self._boot_identity_digest,
                "memory_bytes": self._reserved_memory_bytes,
                "pids": self._reserved_pids,
                "fds": self._reserved_fds,
                "storage": {
                    capacity_id: {
                        "bytes": self._reserved_storage_bytes.get(
                            capacity_id, 0
                        ),
                        "inodes": self._reserved_storage_inodes.get(
                            capacity_id, 0
                        ),
                    }
                    for capacity_id in storage_ids
                },
            }
        )

    def _publish_local_state_locked(self) -> None:
        state_path = self._state_path(self._owner_id)
        if self._local_is_zero_locked():
            try:
                state_path.unlink()
            except FileNotFoundError:
                pass
            self._release_owner_lock_locked()
            return
        self._ensure_owner_lock_locked()
        atomic_replace_bytes(
            state_path,
            self._encode_local_state_locked(),
        )

    def _owner_is_live_locked(self, owner_id: str) -> bool:
        if owner_id == self._owner_id and self._owner_lock is not None:
            return True
        probe = InterprocessFileLock(
            self._owner_lock_path(owner_id),
            blocking=False,
        )
        try:
            probe.__enter__()
        except InterprocessLockBusy:
            return True
        else:
            probe.__exit__(None, None, None)
            return False

    def _prune_stale_states_locked(self) -> None:
        for path in tuple(self._directory.glob("owner-*.json")):
            name = path.name
            owner_id = name[len("owner-") : -len(".json")]
            if (
                len(owner_id) != 64
                or any(ch not in "0123456789abcdef" for ch in owner_id)
            ):
                raise RuntimeError(
                    f"invalid resource reservation owner state: {name}"
                )
            if self._owner_is_live_locked(owner_id):
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            lock_path = self._owner_lock_path(owner_id)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    def _decode_state_locked(self, path: Path) -> dict[str, object]:
        encoded = path.read_bytes()
        raw = strict_json_loads(encoded)
        if not isinstance(raw, dict):
            raise RuntimeError("resource reservation state must be an object")
        if canonical_bytes(raw) != encoded:
            raise RuntimeError(
                "resource reservation state is not canonical"
            )
        expected = {
            "schema",
            "owner_id",
            "host_identity_digest",
            "boot_identity_digest",
            "memory_bytes",
            "pids",
            "fds",
            "storage",
        }
        if set(raw) != expected or raw.get("schema") != self._SCHEMA:
            raise RuntimeError("resource reservation state schema drifted")
        owner_id = raw.get("owner_id")
        if (
            type(owner_id) is not str
            or path != self._state_path(owner_id)
        ):
            raise RuntimeError("resource reservation owner identity drifted")
        if (
            raw.get("host_identity_digest") != self._host_identity_digest
            or raw.get("boot_identity_digest") != self._boot_identity_digest
        ):
            raise RuntimeError(
                "resource reservation state belongs to another host/boot"
            )
        for key in ("memory_bytes", "pids", "fds"):
            value = raw.get(key)
            if type(value) is not int or value < 0:
                raise RuntimeError(
                    f"resource reservation {key} is invalid"
                )
        storage = raw.get("storage")
        if not isinstance(storage, dict):
            raise RuntimeError("resource reservation storage is invalid")
        for capacity_id, row in storage.items():
            if (
                type(capacity_id) is not str
                or not capacity_id.strip()
                or not isinstance(row, dict)
                or set(row) != {"bytes", "inodes"}
            ):
                raise RuntimeError(
                    "resource reservation storage row is invalid"
                )
            for key in ("bytes", "inodes"):
                value = row.get(key)
                if type(value) is not int or value < 0:
                    raise RuntimeError(
                        "resource reservation storage value is invalid"
                    )
        return raw

    def _live_states_locked(self) -> tuple[dict[str, object], ...]:
        self._prune_stale_states_locked()
        rows: list[dict[str, object]] = []
        for path in sorted(self._directory.glob("owner-*.json")):
            owner_id = path.name[len("owner-") : -len(".json")]
            if not self._owner_is_live_locked(owner_id):
                continue
            rows.append(self._decode_state_locked(path))
        return tuple(rows)

    def reserved_demand(self) -> ResourceCompetitionDemand:
        with self.lock:
            rows = self._live_states_locked()
            return ResourceCompetitionDemand(
                memory_bytes_per_permit=sum(
                    int(row["memory_bytes"]) for row in rows
                ),
                pids_per_permit=sum(int(row["pids"]) for row in rows),
                fds_per_permit=sum(int(row["fds"]) for row in rows),
            )

    def reserved_storage_for(self, capacity_id: str) -> tuple[int, int]:
        if type(capacity_id) is not str or not capacity_id.strip():
            raise ValueError("storage reservation capacity_id is required")
        with self.lock:
            reserved_bytes = 0
            reserved_inodes = 0
            for row in self._live_states_locked():
                storage = row["storage"]
                assert isinstance(storage, dict)
                value = storage.get(capacity_id)
                if value is None:
                    continue
                assert isinstance(value, dict)
                reserved_bytes += int(value["bytes"])
                reserved_inodes += int(value["inodes"])
            return reserved_bytes, reserved_inodes

    def reserve(
        self,
        demand: ResourceCompetitionDemand,
        *,
        permit_count: int,
        storage: tuple[_StorageReservation, ...],
    ) -> tuple[_StorageReservation, ...]:
        if type(permit_count) is not int or permit_count <= 0:
            raise ValueError(
                "resource reservation permit_count must be positive"
            )
        if type(storage) is not tuple:
            raise TypeError("storage reservations must be tuple")
        with self.lock:
            self._reserved_memory_bytes += (
                demand.memory_bytes_per_permit * permit_count
            )
            self._reserved_pids += demand.pids_per_permit * permit_count
            self._reserved_fds += demand.fds_per_permit * permit_count
            for row in storage:
                if type(row) is not _StorageReservation:
                    raise TypeError("storage reservation row must be typed")
                if row.bytes_per_permit:
                    self._reserved_storage_bytes[row.capacity_id] = (
                        self._reserved_storage_bytes.get(row.capacity_id, 0)
                        + row.bytes_per_permit * permit_count
                    )
                if row.inodes_per_permit:
                    self._reserved_storage_inodes[row.capacity_id] = (
                        self._reserved_storage_inodes.get(
                            row.capacity_id, 0
                        )
                        + row.inodes_per_permit * permit_count
                    )
            self._publish_local_state_locked()
            return storage

    def release_one(
        self,
        demand: ResourceCompetitionDemand,
        *,
        storage: tuple[_StorageReservation, ...],
    ) -> None:
        with self.lock:
            next_memory = (
                self._reserved_memory_bytes
                - demand.memory_bytes_per_permit
            )
            next_pids = self._reserved_pids - demand.pids_per_permit
            next_fds = self._reserved_fds - demand.fds_per_permit
            if min(next_memory, next_pids, next_fds) < 0:
                raise RuntimeError(
                    "resource competition reservation accounting underflow"
                )
            self._reserved_memory_bytes = next_memory
            self._reserved_pids = next_pids
            self._reserved_fds = next_fds

            for row in storage:
                for reservations, amount, label in (
                    (
                        self._reserved_storage_bytes,
                        row.bytes_per_permit,
                        "storage bytes",
                    ),
                    (
                        self._reserved_storage_inodes,
                        row.inodes_per_permit,
                        "storage inodes",
                    ),
                ):
                    if amount <= 0:
                        continue
                    remaining = (
                        reservations.get(row.capacity_id, 0) - amount
                    )
                    if remaining < 0:
                        raise RuntimeError(
                            "resource competition "
                            f"{label} reservation accounting underflow"
                        )
                    if remaining:
                        reservations[row.capacity_id] = remaining
                    else:
                        reservations.pop(row.capacity_id, None)
            self._publish_local_state_locked()


class _ResourceCompetitionLease:
    """Delegate permit plus fail-closed logical resource reservation."""

    def __init__(
        self,
        delegate: ExecutionPermitLeasePort,
        release_reservation: Callable[[], None],
    ) -> None:
        self._delegate = delegate
        self._release_reservation = release_reservation
        self._released = False
        self._lock = Lock()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            # Do not drop logical capacity before the underlying permit is
            # actually released. If delegate release fails, later admission
            # must continue treating this demand as owned/unknown.
            self._delegate.release()
            self._release_reservation()
            self._released = True


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
        reservations: ResourceCompetitionReservationLedger | None = None,
    ) -> None:
        self._delegate = delegate
        self._observer = observer
        self._storage_observer = storage_observer
        self._network_observer = network_observer
        self._policy = policy
        self._intents: dict[str, AdmissionIntent] = {}
        self._demands: dict[str, ResourceCompetitionDemand] = {}
        self._reservations = (
            ResourceCompetitionReservationLedger()
            if reservations is None
            else reservations
        )
        if not isinstance(
            self._reservations,
            ResourceCompetitionReservationLedger,
        ):
            raise TypeError(
                "resource competition reservations must be a typed ledger"
            )
        self._reservation_lock = self._reservations.lock

    def register_group(
        self,
        group_id: str,
        *,
        identity: AdmissionIdentity,
        intent: AdmissionIntent = AdmissionIntent(),
    ) -> None:
        self._delegate.register_group(group_id, identity=identity, intent=intent)
        self._intents[group_id] = intent
        self._demands[group_id] = ResourceCompetitionDemand()

    def set_group_demand(
        self,
        group_id: str,
        demand: ResourceCompetitionDemand,
    ) -> None:
        if group_id not in self._intents:
            raise KeyError(
                "execution group is not registered with resource competition gate: "
                f"{group_id}"
            )
        if not isinstance(demand, ResourceCompetitionDemand):
            raise TypeError(
                "resource competition group demand must be ResourceCompetitionDemand"
            )
        self._demands[group_id] = demand

    def unregister_group(self, group_id: str) -> None:
        self._delegate.unregister_group(group_id)
        self._intents.pop(group_id, None)
        self._demands.pop(group_id, None)

    @staticmethod
    def _effective_demand(
        demand: ResourceCompetitionDemand,
        lane_kind: ExecutionLaneKind,
    ) -> ResourceCompetitionDemand:
        del lane_kind
        # Physical demand is authoritative regardless of execution lane.  Lane
        # kind selects soft contention policy, never hard-capacity ownership.
        return demand

    def _reserved_demand(self) -> ResourceCompetitionDemand:
        return self._reservations.reserved_demand()

    def _reserved_storage_for(self, capacity_id: str) -> tuple[int, int]:
        return self._reservations.reserved_storage_for(capacity_id)

    def _reserve_demand(
        self,
        demand: ResourceCompetitionDemand,
        *,
        permit_count: int,
        storage: tuple[_StorageReservation, ...],
    ) -> tuple[_StorageReservation, ...]:
        return self._reservations.reserve(
            demand,
            permit_count=permit_count,
            storage=storage,
        )

    def _release_one_demand(
        self,
        demand: ResourceCompetitionDemand,
        *,
        storage: tuple[_StorageReservation, ...],
    ) -> None:
        self._reservations.release_one(
            demand,
            storage=storage,
        )

    def _status(self) -> HostRuntimeStatus | None:
        try:
            snapshot = self._observer.snapshot()
        except Exception:
            return None
        if not snapshot.available:
            return None
        rows = tuple(row for row in snapshot.hosts if row.available)
        return rows[0] if rows else None

    def _storage_status(
        self,
        path: Path | None = None,
    ) -> SharedStoragePressureStatus | None:
        if self._storage_observer is None:
            return None
        try:
            status = self._storage_observer.snapshot(path)
        except Exception:
            return SharedStoragePressureStatus(
                False,
                detail="storage-observer-failed",
            )
        return status

    def _resolved_storage_capacities(
        self,
        demand: ResourceCompetitionDemand,
    ) -> tuple[tuple[_ResolvedStorageCapacity, ...], bool]:
        if not demand.storage_targets:
            return (), False
        if self._storage_observer is None:
            return (), True

        grouped: dict[str, _ResolvedStorageCapacity] = {}
        unavailable = False
        for target in demand.storage_targets:
            status = self._storage_status(target.path)
            if (
                status is None
                or not status.available
                or status.capacity_id is None
            ):
                unavailable = True
                continue
            existing = grouped.get(status.capacity_id)
            if existing is None:
                grouped[status.capacity_id] = _ResolvedStorageCapacity(
                    status.capacity_id,
                    status,
                    target.bytes_per_permit,
                    target.inodes_per_permit,
                )
                continue

            existing_status = existing.status
            total_bytes = (
                None
                if existing_status.total_bytes is None or status.total_bytes is None
                else max(existing_status.total_bytes, status.total_bytes)
            )
            free_inodes = (
                None
                if existing_status.free_inodes is None or status.free_inodes is None
                else min(existing_status.free_inodes, status.free_inodes)
            )
            grouped[status.capacity_id] = _ResolvedStorageCapacity(
                status.capacity_id,
                SharedStoragePressureStatus(
                    True,
                    free_bytes=min(
                        existing_status.free_bytes,
                        status.free_bytes,
                    ),
                    free_inodes=free_inodes,
                    capacity_id=status.capacity_id,
                    total_bytes=total_bytes,
                ),
                existing.bytes_per_permit + target.bytes_per_permit,
                existing.inodes_per_permit + target.inodes_per_permit,
            )
        return (
            tuple(grouped[key] for key in sorted(grouped)),
            unavailable,
        )

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
        *,
        resolved_storage: tuple[_ResolvedStorageCapacity, ...] | None = None,
        storage_unavailable: bool | None = None,
    ) -> str | None:
        intent = self._intents.get(group_id)
        if intent is None:
            raise KeyError(f"execution group is not registered with resource competition gate: {group_id}")
        demand = self._effective_demand(
            self._demands.get(group_id, ResourceCompetitionDemand()),
            lane_kind,
        )
        critical = intent.priority is ExecutionPriority.CRITICAL
        zero_incremental_demand = (
            demand.memory_bytes_per_permit == 0
            and demand.pids_per_permit == 0
            and demand.fds_per_permit == 0
            and not demand.storage_targets
        )
        reserved = self._reserved_demand()

        # Critical control-plane work (lease renewal, checkpoint, teardown) must
        # remain runnable under pressure when it adds no physical demand. A
        # critical workload that does consume resources is still fenced by hard
        # residual-capacity checks below; priority only bypasses soft contention.
        if critical and zero_incremental_demand:
            status = self._status()
            if (
                status is not None
                and lane_kind is ExecutionLaneKind.CPU
                and status.effective_cpu_cores <= 0
            ):
                return "cpu-capacity"
            return None

        status = self._status()
        if status is None:
            return (
                "host-runtime-unavailable"
                if self._policy.fail_closed_when_runtime_unavailable
                else None
            )

        required_memory = (
            self._policy.min_available_memory_bytes
            + reserved.memory_bytes_per_permit
            + demand.memory_bytes_per_permit * permit_count
        )
        if status.available_memory_bytes < required_memory:
            return "memory-headroom"
        if status.available_pids is None:
            if (
                self._policy.fail_closed_when_runtime_unavailable
                and (
                    self._policy.min_available_pids > 0
                    or demand.pids_per_permit * permit_count > 0
                )
            ):
                return "pid-runtime-unavailable"
        elif status.available_pids < (
            self._policy.min_available_pids
            + reserved.pids_per_permit
            + demand.pids_per_permit * permit_count
        ):
            return "pid-headroom"

        if status.available_fds is None:
            if (
                self._policy.fail_closed_when_runtime_unavailable
                and (
                    self._policy.min_available_fds > 0
                    or demand.fds_per_permit * permit_count > 0
                )
            ):
                return "fd-runtime-unavailable"
        elif status.available_fds < (
            self._policy.min_available_fds
            + reserved.fds_per_permit
            + demand.fds_per_permit * permit_count
        ):
            return "fd-headroom"

        if not critical:
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
            if not critical:
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

        io_lane = lane_kind in {
            ExecutionLaneKind.BLOCKING_IO,
            ExecutionLaneKind.ASYNC_IO,
        }

        if resolved_storage is None:
            resolved_storage, observed_storage_unavailable = (
                self._resolved_storage_capacities(demand)
            )
            if storage_unavailable is None:
                storage_unavailable = observed_storage_unavailable
        elif storage_unavailable is None:
            storage_unavailable = False
        if (
            storage_unavailable
            and self._policy.fail_closed_when_runtime_unavailable
        ):
            return "storage-runtime-unavailable"

        for storage_demand in resolved_storage:
            storage = storage_demand.status
            (
                reserved_storage_bytes,
                reserved_storage_inodes,
            ) = self._reserved_storage_for(storage_demand.capacity_id)

            projected_free_bytes = (
                storage.free_bytes
                - reserved_storage_bytes
                - storage_demand.bytes_per_permit * permit_count
            )
            if projected_free_bytes < self._policy.min_storage_free_bytes:
                return "storage-byte-headroom"

            if self._policy.min_storage_free_fraction > 0.0:
                if storage.total_bytes is None:
                    if self._policy.fail_closed_when_runtime_unavailable:
                        return "storage-runtime-unavailable"
                elif (
                    projected_free_bytes / storage.total_bytes
                    < self._policy.min_storage_free_fraction
                ):
                    return "storage-fraction-headroom"

            if storage.free_inodes is None:
                if (
                    self._policy.fail_closed_when_runtime_unavailable
                    and (
                        self._policy.min_storage_free_inodes > 0
                        or storage_demand.inodes_per_permit * permit_count > 0
                    )
                ):
                    return "storage-inode-runtime-unavailable"
            else:
                projected_free_inodes = (
                    storage.free_inodes
                    - reserved_storage_inodes
                    - storage_demand.inodes_per_permit * permit_count
                )
                if (
                    projected_free_inodes
                    < self._policy.min_storage_free_inodes
                ):
                    return "storage-inode-headroom"

        if io_lane:
            if (
                not critical
                and self._network_observer is not None
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
            if not critical:
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
            if intent.reject_if_wait_required:
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
            blocking_wait(sleep_for)

    def try_acquire(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> ExecutionPermitLeasePort | None:
        """Attempt one permit without waiting on logical or physical pressure."""

        if group_id not in self._intents:
            raise KeyError(
                "execution group is not registered with resource competition gate: "
                f"{group_id}"
            )
        if self._cancelled(cancellation):
            raise TaskCancelled(
                cancellation.reason or "resource competition admission cancelled"
            )
        if deadline is not None and deadline.expired:
            raise TimeoutError("resource competition admission deadline expired")
        if not self.decision(group_id, lane_kind).admitted:
            return None

        lease = self._delegate.try_acquire(
            group_id,
            lane_kind,
            deadline=deadline,
            cancellation=cancellation,
        )
        if lease is None:
            return None

        effective_demand = self._effective_demand(
            self._demands.get(group_id, ResourceCompetitionDemand()),
            lane_kind,
        )
        owned_storage = ()
        try:
            with self._reservation_lock:
                resolved_storage, storage_unavailable = (
                    self._resolved_storage_capacities(effective_demand)
                )
                reason = self._competition_reason(
                    group_id,
                    lane_kind,
                    1,
                    resolved_storage=resolved_storage,
                    storage_unavailable=storage_unavailable,
                )
                if reason is not None:
                    lease.release()
                    return None
                storage_reservations = tuple(
                    _StorageReservation(
                        row.capacity_id,
                        row.bytes_per_permit,
                        row.inodes_per_permit,
                    )
                    for row in resolved_storage
                )
                owned_storage = self._reserve_demand(
                    effective_demand,
                    permit_count=1,
                    storage=storage_reservations,
                )
        except BaseException:
            lease.release()
            raise

        return _ResourceCompetitionLease(
            lease,
            lambda owned_demand=effective_demand, storage=owned_storage:
                self._release_one_demand(
                    owned_demand,
                    storage=storage,
                ),
        )

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
        wait_started_monotonic = time.monotonic()
        deadline = intent.constrain_wait_deadline(
            deadline,
            started_monotonic=wait_started_monotonic,
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

            effective_demand = self._effective_demand(
                self._demands.get(group_id, ResourceCompetitionDemand()),
                lane_kind,
            )
            try:
                with self._reservation_lock:
                    (
                        resolved_storage,
                        storage_unavailable,
                    ) = self._resolved_storage_capacities(
                        effective_demand
                    )
                    reason = self._competition_reason(
                        group_id,
                        lane_kind,
                        permit_count,
                        resolved_storage=resolved_storage,
                        storage_unavailable=storage_unavailable,
                    )
                    decision = (
                        ResourceCompetitionDecision(True)
                        if reason is None
                        else ResourceCompetitionDecision(
                            False,
                            reason=reason,
                            competition_class=self._competition_class(reason),
                        )
                    )
                    if decision.admitted:
                        storage_reservations = tuple(
                            _StorageReservation(
                                row.capacity_id,
                                row.bytes_per_permit,
                                row.inodes_per_permit,
                            )
                            for row in resolved_storage
                        )
                        owned_storage = self._reserve_demand(
                            effective_demand,
                            permit_count=permit_count,
                            storage=storage_reservations,
                        )

            except BaseException:
                self._release_delegate_leases(leases)
                raise
            if decision.admitted:
                return tuple(
                    _ResourceCompetitionLease(
                        lease,
                        lambda owned_demand=effective_demand, owned_storage=owned_storage: self._release_one_demand(
                            owned_demand,
                            storage=owned_storage,
                        ),
                    )
                    for lease in leases
                )

            self._release_delegate_leases(leases)
            if intent.reject_if_wait_required:
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
    "ResourceCompetitionDemand",
    "ResourceCompetitionPolicy",
    "ResourceCompetitionReservationLedger",
    "SharedNetworkPressureObserverPort",
    "SharedNetworkPressureStatus",
    "SharedStoragePressureObserverPort",
    "SharedStoragePressureStatus",
    "StorageCompetitionDemand",
]
