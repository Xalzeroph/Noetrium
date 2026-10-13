from __future__ import annotations

from noetrium_platform.foundation.kernel.unit import NoetriumUnit

from noetrium_platform.foundation.kernel.kernel import (
    blocking_wait,
    canonical_digest,
    thaw_json,
    LocalLeaseClock,
)
from dataclasses import dataclass
from enum import StrEnum
import math
import os
from pathlib import Path
from threading import Lock, RLock, local
import time
from uuid import uuid4
from typing import Callable, Protocol

from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)

from noetrium_platform.foundation.kernel.concurrency.api import (
    CancellationTokenPort,
    Deadline,
    ExecutionLaneKind,
    ExecutionPermitLeasePort,
    TaskCancelled,
)
from noetrium_platform.infrastructure.resources.authority import (
    UniversalResourceAuthority,
)
from noetrium_platform.infrastructure.resources.authority import (
    claim_field,
    is_authority_lease,
    lease_field,
    resource_claim,
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

    cpu_cores_per_permit: int = 0
    memory_bytes_per_permit: int = 0
    pids_per_permit: int = 0
    fds_per_permit: int = 0
    storage_targets: tuple[StorageCompetitionDemand, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "cpu_cores_per_permit",
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
        "cpu-headroom",
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
        "adaptive-pressure",
    }
)

_RESERVATION_RECOVERY_REASONS = frozenset(
    {
        "cpu-headroom",
        "memory-headroom",
        "pid-headroom",
        "fd-headroom",
        "storage-byte-headroom",
        "storage-fraction-headroom",
        "storage-inode-headroom",
    }
)


@dataclass(frozen=True, slots=True)
class ResourceCompetitionPolicy:
    """Hard-safety admission policy for shared multi-user hosts.

    Noetrium remains work-conserving when other users arrive. CPU load and
    durable reservations determine residual CPU ownership while PSI continuously
    contracts only the admission window for new non-critical work. Hard
    admission is defined directly against the operating
    system's residual-capacity authorities (MemAvailable, cgroup PID capacity,
    process FD limit and filesystem bavail/ffree) plus durable Noetrium
    reservations.  Defaults therefore add no machine-independent magic
    headroom. Soft contention contracts continuously from live PSI through the
    admission algorithm rather than a fixed concurrency threshold. CRITICAL
    zero-demand control/recovery groups bypass workload pressure so fencing,
    lease renewal, checkpointing, and teardown cannot starve. CRITICAL work
    that declares physical demand still obeys hard residual-capacity fences.
    External processes are never signalled, reniced, deleted, or otherwise
    mutated by this policy.
    """

    min_available_memory_bytes: int = 0
    min_available_pids: int = 0
    min_available_fds: int = 0
    min_storage_free_bytes: int = 0
    min_storage_free_inodes: int = 0
    min_storage_free_fraction: float = 0.0
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
    """Stateless linearization boundary around observe + Authority claim."""

    def __init__(self, reservations: "ResourceCompetitionReservations") -> None:
        self._reservations = reservations

    def __enter__(self) -> "_ResourceCompetitionReservationLock":
        self._reservations._enter_transaction()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._reservations._exit_transaction(exc_type, exc, traceback)


def _default_resource_competition_directory() -> Path:
    reading = LocalLeaseClock().read()
    return (
        runtime_coordination_root()
        / "resource-competition"
        / runtime_coordination_user_namespace()
        / reading.host_identity_digest
        / reading.boot_identity_digest
    )


@dataclass(frozen=True, slots=True)
class _ResourceCompetitionReservationToken:
    claim_id: str
    resource_key: str


class ResourceCompetitionReservations:
    """Authority-backed host reservation projection.

    Reservation truth is ordinary ``resource.claim`` Units in the sole
    UniversalResourceAuthority.  The filesystem contains only one stateless
    kernel mutex that linearizes physical observation with claim admission; no
    reservation JSON, owner state, tombstone or owner lock is authoritative.

    Every permit owns one exact claim.  Claims reference the pool's Authority
    TTL lease through ``owner_lease_id`` so crash expiry is reconciled by the
    same orphan-claim machinery used by every other resource.
    """

    _KIND = "resource-competition-reservation"

    def __init__(
        self,
        authority: UniversalResourceAuthority,
        owner_lease,
        *,
        coordination_directory: Path | None = None,
    ) -> None:
        if not isinstance(authority, UniversalResourceAuthority):
            raise TypeError(
                "resource competition reservations require UniversalResourceAuthority"
            )
        if not is_authority_lease(owner_lease):
            raise TypeError("resource competition reservations require Authority owner lease")
        if bool(lease_field(owner_lease, "released")):
            raise ValueError("resource competition owner lease is already released")
        self._authority = authority
        self._owner_lease = owner_lease
        self._owner_lease_id = str(lease_field(owner_lease, "lease_id"))
        reading = LocalLeaseClock().read()
        self._host_identity_digest = reading.host_identity_digest
        self._boot_identity_digest = reading.boot_identity_digest
        self._holder_key = "resource-competition:" + canonical_digest(
            {
                "host_identity_digest": self._host_identity_digest,
                "boot_identity_digest": self._boot_identity_digest,
            }
        )
        # All permits on one host boot share one logical Authority resource.
        # Affine ownership lives in each claim's unique holder/claim identity,
        # not in a throwaway generation per permit. This makes generation state
        # O(host boots) instead of O(task submissions).
        self._resource_key = self._holder_key + ":capacity"
        self._resource_generation = self._authority.ensure_generation(
            self._resource_key
        ).generation
        directory = (
            _default_resource_competition_directory()
            if coordination_directory is None
            else Path(coordination_directory).absolute()
        )
        directory.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            try:
                directory.chmod(0o700)
            except OSError:
                pass
        self._local_lock = RLock()
        self._thread_state = local()
        self._global_guard = InterprocessFileLock(
            directory / "reservation-linearization.lock"
        )
        self._transaction_lock = _ResourceCompetitionReservationLock(self)
        self._closed = False

    @property
    def lock(self) -> _ResourceCompetitionReservationLock:
        return self._transaction_lock

    @property
    def owner_lease(self):
        return self._owner_lease

    def replace_owner_lease(self, lease) -> None:
        if not is_authority_lease(lease):
            raise TypeError("resource competition owner replacement must be Authority lease")
        if str(lease_field(lease, "lease_id")) != self._owner_lease_id:
            raise RuntimeError("resource competition owner lease identity drifted")
        self._owner_lease = lease

    def _enter_transaction(self) -> None:
        self._local_lock.acquire()
        depth = int(getattr(self._thread_state, "depth", 0))
        if depth:
            self._thread_state.depth = depth + 1
            return
        try:
            self._global_guard.__enter__()
            self._thread_state.depth = 1
            # Recovery must never execute while the host-wide physical
            # linearization mutex is held. A slow Authority writer/recovery
            # transaction here would serialize unrelated research workloads.
            self._thread_state.claims = None
            self._thread_state.aggregate = None
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
        self._thread_state.claims = None
        self._thread_state.aggregate = None
        try:
            self._global_guard.__exit__(exc_type, exc, traceback)
        finally:
            self._local_lock.release()

    @staticmethod
    def _claim_attributes(claim) -> dict[str, object]:
        attrs = thaw_json(claim_field(claim, "attributes") or {})
        assert isinstance(attrs, dict)
        if attrs.get("kind") != ResourceCompetitionReservations._KIND:
            raise RuntimeError(
                "resource competition holder contains non-reservation claim"
            )
        return attrs

    def _claims_locked(self):
        if int(getattr(self._thread_state, "depth", 0)) <= 0:
            raise RuntimeError(
                "resource competition Authority snapshot requires transaction"
            )
        cached = getattr(self._thread_state, "claims", None)
        if cached is not None:
            return cached
        snapshot = self._authority.snapshot_for_resource_keys(
            frozenset({self._resource_key})
        )
        rows = tuple(snapshot.claims)
        for row in rows:
            self._claim_attributes(row)
        self._thread_state.claims = rows
        return rows

    @classmethod
    def _aggregate_claims(
        cls,
        claims,
    ) -> tuple[
        int,
        int,
        int,
        int,
        dict[str, tuple[int, int]],
        dict[ExecutionLaneKind, int],
    ]:
        cpu_cores = 0
        memory_bytes = 0
        pids = 0
        fds = 0
        storage_totals: dict[str, tuple[int, int]] = {}
        lane_totals: dict[ExecutionLaneKind, int] = {}
        for claim in claims:
            attrs = cls._claim_attributes(claim)
            cpu_cores += int(attrs.get("cpu_cores", 0))
            memory_bytes += int(attrs.get("memory_bytes", 0))
            pids += int(attrs.get("pids", 0))
            fds += int(attrs.get("fds", 0))
            raw_lane = str(attrs.get("lane_kind") or "").strip()
            if raw_lane:
                try:
                    lane = ExecutionLaneKind(raw_lane)
                except ValueError as exc:
                    raise RuntimeError(
                        "resource competition lane reservation drifted"
                    ) from exc
                lane_totals[lane] = lane_totals.get(lane, 0) + 1
            storage = attrs.get("storage", ())
            if not isinstance(storage, (list, tuple)):
                raise RuntimeError("resource competition storage reservation drifted")
            for raw in storage:
                if not isinstance(raw, dict):
                    raise RuntimeError("resource competition storage reservation row drifted")
                capacity_id = str(raw.get("capacity_id") or "").strip()
                if not capacity_id:
                    raise RuntimeError("resource competition storage capacity id drifted")
                bytes_value = int(raw.get("bytes", 0))
                inode_value = int(raw.get("inodes", 0))
                if bytes_value < 0 or inode_value < 0:
                    raise RuntimeError("resource competition storage reservation is negative")
                current_bytes, current_inodes = storage_totals.get(
                    capacity_id,
                    (0, 0),
                )
                storage_totals[capacity_id] = (
                    current_bytes + bytes_value,
                    current_inodes + inode_value,
                )
        return (
            cpu_cores,
            memory_bytes,
            pids,
            fds,
            storage_totals,
            lane_totals,
        )

    def _aggregate_locked(
        self,
    ) -> tuple[
        int,
        int,
        int,
        int,
        dict[str, tuple[int, int]],
        dict[ExecutionLaneKind, int],
    ]:
        if int(getattr(self._thread_state, "depth", 0)) <= 0:
            raise RuntimeError(
                "resource competition aggregate requires transaction"
            )
        cached = getattr(self._thread_state, "aggregate", None)
        if cached is not None:
            return cached
        aggregate = self._aggregate_claims(self._claims_locked())
        self._thread_state.aggregate = aggregate
        return aggregate

    def _invalidate_locked(self) -> None:
        self._thread_state.claims = None
        self._thread_state.aggregate = None

    @property
    def owner_lease_id(self) -> str:
        return self._owner_lease_id

    def reconcile_orphans(self) -> tuple[NoetriumUnit, ...]:
        """Recover expired capacity reservations without a global scan."""

        return tuple(
            self._authority.reconcile_orphan_claims_for_resource_keys(
                frozenset({self._resource_key})
            )
        )

    def reservation_projection(
        self,
    ) -> tuple[
        ResourceCompetitionDemand,
        dict[str, tuple[int, int]],
        dict[ExecutionLaneKind, int],
    ]:
        """Read one transactionally consistent reservation projection.

        Inside the physical linearization transaction, reuse its exact cached
        Authority cut. Outside that transaction, a sparse holder snapshot is
        sufficient for advisory admission; final claim publication always
        revalidates under the physical mutex.
        """
        if int(getattr(self._thread_state, "depth", 0)) > 0:
            (
                cpu_cores,
                memory_bytes,
                pids,
                fds,
                storage,
                lane_totals,
            ) = self._aggregate_locked()
        else:
            snapshot = self._authority.snapshot_for_resource_keys(
                frozenset({self._resource_key})
            )
            (
                cpu_cores,
                memory_bytes,
                pids,
                fds,
                storage,
                lane_totals,
            ) = self._aggregate_claims(snapshot.claims)
        return (
            ResourceCompetitionDemand(
                cpu_cores_per_permit=cpu_cores,
                memory_bytes_per_permit=memory_bytes,
                pids_per_permit=pids,
                fds_per_permit=fds,
            ),
            dict(storage),
            dict(lane_totals),
        )

    def reserved_demand(self) -> ResourceCompetitionDemand:
        demand, _storage, _lanes = self.reservation_projection()
        return demand

    def reserved_storage_for(self, capacity_id: str) -> tuple[int, int]:
        if type(capacity_id) is not str or not capacity_id.strip():
            raise ValueError("storage reservation capacity_id is required")
        _demand, storage, _lanes = self.reservation_projection()
        return storage.get(capacity_id, (0, 0))

    def reserve(
        self,
        demand: ResourceCompetitionDemand,
        *,
        lane_kind: ExecutionLaneKind,
        permit_count: int,
        storage: tuple[_StorageReservation, ...],
    ) -> tuple[_ResourceCompetitionReservationToken, ...]:
        if type(permit_count) is not int or permit_count <= 0:
            raise ValueError("resource reservation permit_count must be positive")
        if not isinstance(lane_kind, ExecutionLaneKind):
            raise TypeError(
                "resource reservation lane_kind must be ExecutionLaneKind"
            )
        if type(storage) is not tuple or any(
            type(row) is not _StorageReservation for row in storage
        ):
            raise TypeError("storage reservations must be typed tuple")
        with self.lock:
            permit_holders = tuple(
                self._holder_key + ":permit:" + uuid4().hex
                for _index in range(permit_count)
            )
            claims: list[NoetriumUnit] = []
            for permit_holder in permit_holders:
                claim_id = "resource-competition:" + canonical_digest(
                    {
                        "resource_key": self._resource_key,
                        "holder_key": permit_holder,
                        "owner_lease_id": self._owner_lease_id,
                    }
                )
                claims.append(
                    resource_claim(
                        claim_id=claim_id,
                        resource_key=self._resource_key,
                        holder_key=permit_holder,
                        generation=self._resource_generation,
                        owner_scope=lease_field(
                            self._owner_lease,
                            "owner_scope",
                        ),
                        scope_generation=int(
                            lease_field(
                                self._owner_lease,
                                "scope_generation",
                            )
                        ),
                        scope_lease_id=lease_field(
                            self._owner_lease,
                            "scope_lease_id",
                        ),
                        owner_lease_id=self._owner_lease_id,
                        attributes={
                            "kind": self._KIND,
                            "owner_lease_id": self._owner_lease_id,
                            "host_identity_digest": self._host_identity_digest,
                            "boot_identity_digest": self._boot_identity_digest,
                            "lane_kind": lane_kind.value,
                            "cpu_cores": demand.cpu_cores_per_permit,
                            "memory_bytes": demand.memory_bytes_per_permit,
                            "pids": demand.pids_per_permit,
                            "fds": demand.fds_per_permit,
                            "storage": [
                                {
                                    "capacity_id": row.capacity_id,
                                    "bytes": row.bytes_per_permit,
                                    "inodes": row.inodes_per_permit,
                                }
                                for row in storage
                            ],
                        },
                    )
                )
            try:
                admitted = self._authority.admit_bundle(
                    tuple((claim,) for claim in claims)
                )
            finally:
                self._invalidate_locked()
            return tuple(
                _ResourceCompetitionReservationToken(
                    str(claim_field(claim, "claim_id")),
                    str(claim_field(claim, "resource_key")),
                )
                for claim in admitted
            )

    def release(self, token: _ResourceCompetitionReservationToken) -> None:
        if type(token) is not _ResourceCompetitionReservationToken:
            raise TypeError("resource competition release requires reservation token")
        # Claim release is monotone with respect to admission safety: it can only
        # increase residual capacity.  The Authority transaction remains the
        # physical source of truth (including the realization-retirement fence),
        # but release does not need the host-wide admission linearization mutex.
        # A concurrent admission that observed the claim just before this release
        # is merely conservative for one decision; it can never over-admit.
        self._authority.release_claim(token.claim_id)
        # Transaction projections are thread-local.  If release occurs from a
        # callback nested in a reservation transaction, invalidate only that
        # thread's cached cut; other transactions retain their conservative cut.
        self._invalidate_locked()

    def close(self) -> None:
        if self._closed:
            return
        with self.lock:
            errors: list[BaseException] = []
            for claim in self._claims_locked():
                attrs = self._claim_attributes(claim)
                if attrs.get("owner_lease_id") != self._owner_lease_id:
                    continue
                try:
                    self._authority.release_claim(
                        str(claim_field(claim, "claim_id"))
                    )
                except BaseException as exc:
                    errors.append(exc)
            self._invalidate_locked()
            if errors:
                raise BaseExceptionGroup(
                    "resource competition reservation retirement failed",
                    errors,
                )
            self._closed = True


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

    def rollback(self) -> None:
        with self._lock:
            if self._released:
                return
            self._delegate.rollback()
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
        reservations: ResourceCompetitionReservations,
    ) -> None:
        self._delegate = delegate
        self._observer = observer
        self._storage_observer = storage_observer
        self._network_observer = network_observer
        self._policy = policy
        self._intents: dict[str, AdmissionIntent] = {}
        self._demands: dict[str, ResourceCompetitionDemand] = {}
        if not isinstance(reservations, ResourceCompetitionReservations):
            raise TypeError(
                "resource competition reservations must use Universal Resource Authority"
            )
        self._reservations = reservations
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

    @staticmethod
    def _has_incremental_demand(demand: ResourceCompetitionDemand) -> bool:
        return bool(
            demand.cpu_cores_per_permit
            or demand.memory_bytes_per_permit
            or demand.pids_per_permit
            or demand.fds_per_permit
            or demand.storage_targets
        )

    def _reservation_projection(
        self,
    ) -> tuple[
        ResourceCompetitionDemand,
        dict[str, tuple[int, int]],
        dict[ExecutionLaneKind, int],
    ]:
        return self._reservations.reservation_projection()

    @staticmethod
    def _pressure_service_fraction(
        status: HostRuntimeStatus,
        demand: ResourceCompetitionDemand,
        lane_kind: ExecutionLaneKind,
    ) -> float:
        """Return the live bottleneck service fraction without magic thresholds.

        PSI is already a dimensionless fraction of wall time in which runnable
        work stalled on a physical resource.  The minimum residual fraction
        across resources actually consumed by this permit is therefore the
        conservative bottleneck service window.  Missing soft-pressure facts do
        not weaken hard residual-capacity safety; they simply contribute no
        performance contraction.
        """

        residuals = [1.0]

        def include(percent: float | None) -> None:
            if percent is None:
                return
            residuals.append(
                max(0.0, min(1.0, 1.0 - float(percent) / 100.0))
            )

        if demand.cpu_cores_per_permit > 0:
            include(status.cpu_pressure_some_avg10_percent)
        if demand.memory_bytes_per_permit > 0:
            include(status.memory_pressure_some_avg10_percent)
        if (
            lane_kind
            in {ExecutionLaneKind.BLOCKING_IO, ExecutionLaneKind.ASYNC_IO}
            and ResourceCompetitionAdmissionGate._has_incremental_demand(demand)
        ):
            include(status.io_pressure_some_avg10_percent)
        return min(residuals)

    def _reserve_demand(
        self,
        demand: ResourceCompetitionDemand,
        *,
        lane_kind: ExecutionLaneKind,
        permit_count: int,
        storage: tuple[_StorageReservation, ...],
    ) -> tuple[_ResourceCompetitionReservationToken, ...]:
        return self._reservations.reserve(
            demand,
            lane_kind=lane_kind,
            permit_count=permit_count,
            storage=storage,
        )

    def _release_reservation(
        self,
        token: _ResourceCompetitionReservationToken,
    ) -> None:
        self._reservations.release(token)

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
        # storage_targets were already canonicalized by path.  dict insertion
        # order therefore gives a deterministic first-occurrence order for
        # physical capacity ids without a second O(K log K) comparison sort.
        return (
            tuple(grouped.values()),
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
        zero_incremental_demand = not self._has_incremental_demand(demand)
        # A zero-demand permit cannot consume or overbook residual capacity.
        # Keep host/soft-pressure observation semantics, but never serialize
        # pure control/model-I/O work through the cross-process reservation
        # ledger merely to observe an all-zero aggregate contribution.
        if zero_incremental_demand:
            reserved = ResourceCompetitionDemand()
            reserved_storage: dict[str, tuple[int, int]] = {}
            reserved_lanes: dict[ExecutionLaneKind, int] = {}
        else:
            (
                reserved,
                reserved_storage,
                reserved_lanes,
            ) = self._reservation_projection()

        # Critical control-plane work (lease renewal, checkpoint, teardown) must
        # remain runnable under pressure when it adds no physical demand. A
        # critical workload that does consume resources is still fenced by hard
        # residual-capacity checks below; priority only bypasses soft contention.
        if critical and zero_incremental_demand:
            # For non-CPU lanes the answer is independent of host pressure:
            # this permit adds no RAM/PID/FD/storage/network demand and the
            # lane provider already owns its physical concurrency bound.  Do
            # not perform an O(host-observation) /proc scan merely to return
            # the same admission decision.  CPU work still validates that a
            # schedulable core exists.
            if lane_kind is not ExecutionLaneKind.CPU:
                return None
            status = self._status()
            if status is not None and status.effective_cpu_cores <= 0:
                return "cpu-capacity"
            return None

        status = self._status()
        if status is None:
            return (
                "host-runtime-unavailable"
                if self._policy.fail_closed_when_runtime_unavailable
                else None
            )

        if demand.cpu_cores_per_permit > 0:
            effective_cpu_cores = float(status.effective_cpu_cores)
            if effective_cpu_cores <= 0:
                return "cpu-capacity"
            if status.cpu_utilization_percent is None:
                # /proc/stat needs two samples. Until the second observation,
                # load1 is a conservative fail-close fallback; it is never
                # treated as utilization once an actual busy-time sample exists.
                observed_busy_cpu = float(status.cpu_load_1m)
            else:
                observed_busy_cpu = (
                    effective_cpu_cores
                    * float(status.cpu_utilization_percent)
                    / 100.0
                )
            projected_cpu = (
                max(
                    observed_busy_cpu,
                    float(reserved.cpu_cores_per_permit),
                )
                + demand.cpu_cores_per_permit * permit_count
            )
            if projected_cpu > effective_cpu_cores:
                return "cpu-headroom"
            if not critical:
                service_fraction = self._pressure_service_fraction(
                    status,
                    demand,
                    lane_kind,
                )
                if projected_cpu > effective_cpu_cores * service_fraction:
                    return "adaptive-pressure"

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
            ) = reserved_storage.get(storage_demand.capacity_id, (0, 0))

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

    def _decision_after_orphan_recovery(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        permit_count: int,
        incremental_demand: bool,
    ) -> ResourceCompetitionDecision:
        """Return the advisory physical-feasibility cut.

        Global execution fairness/order belongs exclusively to
        UnifiedSchedulingAuthority.  This layer only evaluates residual
        physical capacity/pressure and may reconcile stale capacity claims when
        they are the sole cause of a hard rejection.
        """

        decision = self.decision(
            group_id,
            lane_kind,
            permit_count=permit_count,
        )
        if (
            incremental_demand
            and not decision.admitted
            and decision.reason in _RESERVATION_RECOVERY_REASONS
        ):
            released = self._reservations.reconcile_orphans()
            if released:
                decision = self.decision(
                    group_id,
                    lane_kind,
                    permit_count=permit_count,
                )
        return decision

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
            raise KeyError(
                "execution group is not registered with resource competition gate: "
                f"{group_id}"
            )
        demand = self._effective_demand(
            self._demands.get(group_id, ResourceCompetitionDemand()),
            lane_kind,
        )
        incremental_demand = self._has_incremental_demand(demand)
        while True:
            decision = self._decision_after_orphan_recovery(
                group_id,
                lane_kind,
                permit_count=permit_count,
                incremental_demand=incremental_demand,
            )
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

        leases = self.try_acquire_many(
            group_id,
            lane_kind,
            permit_count=1,
            deadline=deadline,
            cancellation=cancellation,
        )
        if leases is None:
            return None
        if len(leases) != 1:
            self._release_delegate_leases(leases)
            raise RuntimeError(
                "resource competition nonblocking grant cardinality drifted"
            )
        return leases[0]

    def _max_competition_prefix_locked(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        upper_bound: int,
        *,
        incremental_demand: bool,
        resolved_storage: tuple[_ResolvedStorageCapacity, ...],
        storage_unavailable: bool,
    ) -> int:
        """Largest physically admissible prefix for one monotone demand shape."""

        if upper_bound <= 0:
            return 0
        if not incremental_demand:
            return upper_bound

        low = 0
        high = upper_bound
        while low < high:
            probe = (low + high + 1) // 2
            reason = self._competition_reason(
                group_id,
                lane_kind,
                probe,
                resolved_storage=resolved_storage,
                storage_unavailable=storage_unavailable,
            )
            if reason is None:
                low = probe
            else:
                high = probe - 1
        return low

    def try_acquire_up_to(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        max_permit_count: int,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> tuple[ExecutionPermitLeasePort, ...]:
        """Return the largest immediately admissible prefix across policy+physics."""

        if type(max_permit_count) is not int or max_permit_count <= 0:
            raise ValueError(
                "resource competition max_permit_count must be positive"
            )
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

        effective_demand = self._effective_demand(
            self._demands.get(group_id, ResourceCompetitionDemand()),
            lane_kind,
        )
        incremental_demand = self._has_incremental_demand(effective_demand)

        delegate_leases = self._delegate.try_acquire_up_to(
            group_id,
            lane_kind,
            max_permit_count=max_permit_count,
            deadline=deadline,
            cancellation=cancellation,
        )
        if not delegate_leases:
            return ()
        if not incremental_demand:
            return tuple(delegate_leases)

        retained = tuple(delegate_leases)
        owned_tokens: tuple[_ResourceCompetitionReservationToken, ...] = ()
        try:
            with self._reservation_lock:
                resolved_storage, storage_unavailable = (
                    self._resolved_storage_capacities(effective_demand)
                )
                admitted_count = self._max_competition_prefix_locked(
                    group_id,
                    lane_kind,
                    len(retained),
                    incremental_demand=incremental_demand,
                    resolved_storage=resolved_storage,
                    storage_unavailable=storage_unavailable,
                )
                if admitted_count < len(retained):
                    self._rollback_delegate_leases(retained[admitted_count:])
                    retained = retained[:admitted_count]
                if not retained:
                    return ()

                storage_reservations = tuple(
                    _StorageReservation(
                        row.capacity_id,
                        row.bytes_per_permit,
                        row.inodes_per_permit,
                    )
                    for row in resolved_storage
                )
                owned_tokens = self._reserve_demand(
                    effective_demand,
                    lane_kind=lane_kind,
                    permit_count=len(retained),
                    storage=storage_reservations,
                )
        except BaseException:
            self._rollback_delegate_leases(retained)
            raise

        if len(owned_tokens) != len(retained):
            self._rollback_delegate_leases(retained)
            raise RuntimeError(
                "resource competition maximal reservation cardinality drifted"
            )
        return tuple(
            _ResourceCompetitionLease(
                lease,
                lambda reservation=token: self._release_reservation(
                    reservation
                ),
            )
            for lease, token in zip(retained, owned_tokens, strict=True)
        )

    def try_acquire_many(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        permit_count: int,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> tuple[ExecutionPermitLeasePort, ...] | None:
        """Attempt one all-or-none permit batch with no queue or sleep."""

        if type(permit_count) is not int or permit_count <= 0:
            raise ValueError(
                "resource competition nonblocking permit_count must be positive"
            )
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

        effective_demand = self._effective_demand(
            self._demands.get(group_id, ResourceCompetitionDemand()),
            lane_kind,
        )
        incremental_demand = self._has_incremental_demand(effective_demand)
        decision = self._decision_after_orphan_recovery(
            group_id,
            lane_kind,
            permit_count=permit_count,
            incremental_demand=incremental_demand,
        )
        if not decision.admitted:
            return None

        leases = self._delegate.try_acquire_many(
            group_id,
            lane_kind,
            permit_count=permit_count,
            deadline=deadline,
            cancellation=cancellation,
        )
        if leases is None:
            return None
        if len(leases) != permit_count:
            self._release_delegate_leases(leases)
            raise RuntimeError(
                "resource competition delegate returned invalid "
                "nonblocking lease cardinality"
            )

        if not incremental_demand:
            return tuple(leases)

        owned_tokens: tuple[_ResourceCompetitionReservationToken, ...] = ()
        try:
            with self._reservation_lock:
                resolved_storage, storage_unavailable = (
                    self._resolved_storage_capacities(effective_demand)
                )
                reason = self._competition_reason(
                    group_id,
                    lane_kind,
                    permit_count,
                    resolved_storage=resolved_storage,
                    storage_unavailable=storage_unavailable,
                )
                if reason is not None:
                    self._rollback_delegate_leases(leases)
                    return None
                storage_reservations = tuple(
                    _StorageReservation(
                        row.capacity_id,
                        row.bytes_per_permit,
                        row.inodes_per_permit,
                    )
                    for row in resolved_storage
                )
                owned_tokens = self._reserve_demand(
                    effective_demand,
                    lane_kind=lane_kind,
                    permit_count=permit_count,
                    storage=storage_reservations,
                )
        except BaseException:
            self._rollback_delegate_leases(leases)
            raise

        if len(owned_tokens) != permit_count:
            self._release_delegate_leases(leases)
            raise RuntimeError(
                "resource competition reservation cardinality drifted"
            )
        return tuple(
            _ResourceCompetitionLease(
                lease,
                lambda reservation=token: self._release_reservation(
                    reservation
                ),
            )
            for lease, token in zip(leases, owned_tokens, strict=True)
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
    def _rollback_delegate_leases(
        leases: tuple[ExecutionPermitLeasePort, ...],
    ) -> None:
        errors: list[BaseException] = []
        for lease in reversed(leases):
            try:
                lease.rollback()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup(
                "resource competition failed to rollback provisional permits",
                errors,
            )

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
        effective_demand = self._effective_demand(
            self._demands.get(group_id, ResourceCompetitionDemand()),
            lane_kind,
        )
        incremental_demand = self._has_incremental_demand(effective_demand)
        last_pressure_reason: str | None = None

        while True:
            if (
                last_pressure_reason is not None
                and deadline is not None
                and deadline.expired
            ):
                raise TimeoutError(
                    "resource competition admission deadline expired: "
                    f"group={group_id} lane={lane_kind.value} "
                    f"reason={last_pressure_reason}"
                )
            # Scheduling owns ordering. Physical pressure is validated only
            # after the candidate has entered the one fair queue; otherwise
            # local pressure polling becomes a hidden second scheduler.
            leases = self._delegate.acquire_many(
                group_id,
                lane_kind,
                permit_count=permit_count,
                deadline=deadline,
                cancellation=cancellation,
            )
            if len(leases) != permit_count:
                self._rollback_delegate_leases(leases)
                raise RuntimeError(
                    "resource competition delegate returned invalid lease cardinality"
                )

            if self._cancelled(cancellation):
                self._rollback_delegate_leases(leases)
                raise TaskCancelled(
                    cancellation.reason or "resource competition admission cancelled"
                )
            if deadline is not None and deadline.expired:
                self._rollback_delegate_leases(leases)
                raise TimeoutError(
                    "resource competition admission deadline expired after provisional grant"
                )

            owned_tokens: tuple[_ResourceCompetitionReservationToken, ...] = ()
            try:
                with self._reservation_lock:
                    (
                        resolved_storage,
                        storage_unavailable,
                    ) = self._resolved_storage_capacities(effective_demand)
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
                    if decision.admitted and incremental_demand:
                        storage_reservations = tuple(
                            _StorageReservation(
                                row.capacity_id,
                                row.bytes_per_permit,
                                row.inodes_per_permit,
                            )
                            for row in resolved_storage
                        )
                        owned_tokens = self._reserve_demand(
                            effective_demand,
                            lane_kind=lane_kind,
                            permit_count=permit_count,
                            storage=storage_reservations,
                        )
            except BaseException:
                self._rollback_delegate_leases(leases)
                raise

            if decision.admitted:
                if not incremental_demand:
                    return tuple(leases)
                if len(owned_tokens) != len(leases):
                    self._rollback_delegate_leases(leases)
                    raise RuntimeError(
                        "resource competition reservation cardinality drifted"
                    )
                return tuple(
                    _ResourceCompetitionLease(
                        lease,
                        lambda reservation=token: self._release_reservation(
                            reservation
                        ),
                    )
                    for lease, token in zip(leases, owned_tokens, strict=True)
                )

            self._rollback_delegate_leases(leases)
            last_pressure_reason = decision.reason
            if intent.reject_if_wait_required:
                raise AdmissionRejected(
                    "resource competition rejected execution admission after "
                    "provisional grant: "
                    f"group={group_id} lane={lane_kind.value} "
                    f"class={decision.competition_class.value} "
                    f"reason={decision.reason}"
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
    "ResourceCompetitionReservations",
    "SharedNetworkPressureObserverPort",
    "SharedNetworkPressureStatus",
    "SharedStoragePressureObserverPort",
    "SharedStoragePressureStatus",
    "StorageCompetitionDemand",
]
