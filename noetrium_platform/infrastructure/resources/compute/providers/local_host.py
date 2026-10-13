from __future__ import annotations

import math
import os
from pathlib import Path
import platform
import re
from threading import Condition, Lock
from noetrium_platform.infrastructure.resources.compute.api import (
    HostRuntimeSnapshot,
    HostRuntimeStatus,
)


class LocalHostRuntimeObserver:
    """Read-only Linux/posix host pressure facts for opportunistic placement."""

    def __init__(self, *, host_id: str | None = None) -> None:
        resolved = host_id or platform.node()
        if not resolved or not resolved.strip():
            raise ValueError("local host runtime observer requires a host identity")
        self._host_id = resolved.strip()
        self._cpu_sample_lock = Lock()
        self._previous_cpu_sample: tuple[int, int] | None = None
        self._snapshot_condition = Condition()
        self._snapshot_inflight = False
        self._snapshot_generation = 0
        self._last_snapshot: HostRuntimeSnapshot | None = None

    @staticmethod
    def _integer_file(path: Path) -> int | None:
        try:
            value = path.read_text("utf-8", errors="replace").strip()
        except OSError:
            return None
        if value in {"", "max"}:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    @staticmethod
    def _meminfo_bytes(key: str) -> int | None:
        path = Path("/proc/meminfo")
        try:
            lines = path.read_text("utf-8", errors="replace").splitlines()
        except OSError:
            return None
        for line in lines:
            name, separator, raw = line.partition(":")
            if name != key or not separator:
                continue
            match = re.search(r"(\d+)", raw)
            return None if match is None else int(match.group(1)) * 1024
        return None

    @staticmethod
    def _pressure_some_avg10_percent(path: Path) -> float | None:
        try:
            lines = path.read_text("utf-8", errors="replace").splitlines()
        except OSError:
            return None
        for line in lines:
            if not line.startswith("some "):
                continue
            match = re.search(r"(?:^|\s)avg10=([0-9]+(?:\.[0-9]+)?)", line)
            if match is None:
                return None
            value = float(match.group(1))
            return value if math.isfinite(value) and 0.0 <= value <= 100.0 else None
        return None

    @staticmethod
    def _system_available_pids() -> int | None:
        pid_max = LocalHostRuntimeObserver._integer_file(
            Path("/proc/sys/kernel/pid_max")
        )
        if pid_max is None or pid_max <= 0:
            return None
        try:
            fields = Path("/proc/loadavg").read_text(
                "utf-8", errors="replace"
            ).split()
            running_total = fields[3].split("/", 1)
            total_tasks = int(running_total[1])
        except (OSError, IndexError, ValueError):
            return None
        if total_tasks < 0:
            return None
        return max(0, pid_max - total_tasks)

    @staticmethod
    def _available_pids() -> int | None:
        values: list[int] = []
        limit = LocalHostRuntimeObserver._integer_file(
            Path("/sys/fs/cgroup/pids.max")
        )
        current = LocalHostRuntimeObserver._integer_file(
            Path("/sys/fs/cgroup/pids.current")
        )
        if (
            limit is not None
            and current is not None
            and limit >= 0
            and current >= 0
        ):
            values.append(max(0, limit - current))
        system = LocalHostRuntimeObserver._system_available_pids()
        if system is not None:
            values.append(system)
        return None if not values else min(values)

    @staticmethod
    def _system_available_fds() -> int | None:
        try:
            fields = Path("/proc/sys/fs/file-nr").read_text(
                "utf-8", errors="replace"
            ).split()
            allocated = int(fields[0])
            unused = int(fields[1])
            maximum = int(fields[2])
        except (OSError, IndexError, ValueError):
            return None
        if allocated < 0 or unused < 0 or maximum <= 0:
            return None
        in_use = max(0, allocated - unused)
        return max(0, maximum - in_use)

    @staticmethod
    def _available_fds() -> int | None:
        """Return host-global kernel file-handle headroom.

        ResourceCompetitionDemand is host-scoped and aggregated across live
        Noetrium owners. RLIMIT_NOFILE is a per-process ceiling, so mixing it
        into this host fact aliases two different capacity domains and causes
        false admission failures. Process-local descriptor capacity is enforced
        by the execution-runtime boundary that owns that process.
        """
        return LocalHostRuntimeObserver._system_available_fds()

    @staticmethod
    def _affinity_cpu_totals() -> tuple[int, int] | None:
        """Return aggregate total/idle jiffies for CPUs visible to this process."""

        try:
            affinity = set(os.sched_getaffinity(0))
        except (AttributeError, OSError):
            count = os.cpu_count() or 0
            affinity = set(range(max(0, count)))
        if not affinity:
            return None
        try:
            lines = Path("/proc/stat").read_text(
                "utf-8", errors="replace"
            ).splitlines()
        except OSError:
            return None
        total = 0
        idle = 0
        observed: set[int] = set()
        for line in lines:
            if not line.startswith("cpu") or line.startswith("cpu "):
                continue
            fields = line.split()
            label = fields[0]
            suffix = label[3:]
            if not suffix.isdigit():
                continue
            index = int(suffix)
            if index not in affinity:
                continue
            try:
                values = tuple(int(value) for value in fields[1:])
            except ValueError:
                return None
            if len(values) < 4:
                return None
            observed.add(index)
            total += sum(values)
            # Linux cpu statistics: idle + iowait do not consume CPU execution
            # capacity. CPU PSI separately captures runnable-task contention.
            idle += values[3] + (values[4] if len(values) > 4 else 0)
        if observed != affinity or total <= 0:
            return None
        return total, idle

    def _cpu_utilization_percent(self) -> float | None:
        current = self._affinity_cpu_totals()
        if current is None:
            return None
        with self._cpu_sample_lock:
            previous = self._previous_cpu_sample
            self._previous_cpu_sample = current
        if previous is None:
            return None
        total_delta = current[0] - previous[0]
        idle_delta = current[1] - previous[1]
        if total_delta <= 0 or idle_delta < 0:
            return None
        busy_delta = max(0, total_delta - min(total_delta, idle_delta))
        return min(100.0, max(0.0, 100.0 * busy_delta / total_delta))

    @staticmethod
    def _effective_cpu_cores() -> float | None:
        try:
            affinity_count = len(os.sched_getaffinity(0))
        except (AttributeError, OSError):
            affinity_count = os.cpu_count() or 0
        if affinity_count <= 0:
            return None
        effective = float(affinity_count)
        path = Path("/sys/fs/cgroup/cpu.max")
        try:
            fields = path.read_text("utf-8", errors="replace").strip().split()
        except OSError:
            fields = []
        if len(fields) == 2 and fields[0] != "max":
            try:
                quota = int(fields[0])
                period = int(fields[1])
                if quota > 0 and period > 0:
                    effective = min(effective, quota / period)
            except ValueError:
                pass
        return effective if effective > 0 and math.isfinite(effective) else None

    @staticmethod
    def _effective_available_memory() -> int | None:
        available = LocalHostRuntimeObserver._meminfo_bytes("MemAvailable")
        if available is None:
            return None
        limit = LocalHostRuntimeObserver._integer_file(Path("/sys/fs/cgroup/memory.max"))
        current = LocalHostRuntimeObserver._integer_file(Path("/sys/fs/cgroup/memory.current"))
        if limit is not None and current is not None:
            available = min(available, max(0, limit - current))
        return max(0, available)

    def _snapshot_now(self) -> HostRuntimeSnapshot:
        cpu = self._effective_cpu_cores()
        memory = self._effective_available_memory()
        try:
            load = float(os.getloadavg()[0])
        except (AttributeError, OSError):
            load = math.nan
        if cpu is None or memory is None or not math.isfinite(load) or load < 0:
            return HostRuntimeSnapshot(
                False,
                detail="local-host-runtime-facts-unavailable",
            )
        cpu_utilization = self._cpu_utilization_percent()
        return HostRuntimeSnapshot(
            True,
            hosts=(HostRuntimeStatus(
                host_id=self._host_id,
                available=True,
                effective_cpu_cores=cpu,
                cpu_load_1m=load,
                available_memory_bytes=memory,
                cpu_utilization_percent=cpu_utilization,
                cpu_pressure_some_avg10_percent=self._pressure_some_avg10_percent(
                    Path("/proc/pressure/cpu")
                ),
                memory_pressure_some_avg10_percent=self._pressure_some_avg10_percent(
                    Path("/proc/pressure/memory")
                ),
                io_pressure_some_avg10_percent=self._pressure_some_avg10_percent(
                    Path("/proc/pressure/io")
                ),
                available_pids=self._available_pids(),
                available_fds=self._available_fds(),
            ),),
        )

    def snapshot(self) -> HostRuntimeSnapshot:
        """Coalesce only overlapping host observations; never cache by time.

        Admission bursts often ask for the same host cut concurrently. Reading
        /proc, cgroup files and PSI once for those overlapping callers both
        removes redundant I/O and preserves a meaningful CPU-utilization delta.
        Once the producer completes, the very next non-overlapping caller is
        free to observe a fresh cut immediately: there is no TTL or sampling
        interval hidden in this provider.
        """

        condition = self._snapshot_condition
        with condition:
            if self._snapshot_inflight:
                generation = self._snapshot_generation
                while self._snapshot_generation == generation:
                    condition.wait()
                snapshot = self._last_snapshot
                if snapshot is None:
                    raise RuntimeError(
                        "local host runtime snapshot single-flight lost result"
                    )
                return snapshot
            self._last_snapshot = None
            self._snapshot_inflight = True

        try:
            snapshot = self._snapshot_now()
        except BaseException:
            with condition:
                self._snapshot_inflight = False
                self._snapshot_generation += 1
                condition.notify_all()
            raise

        with condition:
            self._last_snapshot = snapshot
            self._snapshot_inflight = False
            self._snapshot_generation += 1
            condition.notify_all()
        return snapshot


__all__ = ["LocalHostRuntimeObserver"]
