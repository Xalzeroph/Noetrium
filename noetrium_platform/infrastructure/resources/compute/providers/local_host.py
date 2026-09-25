from __future__ import annotations

import math
import os
from pathlib import Path
import platform
import re
from time import time
try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX import surface
    resource = None

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
            match = re.search(r"(?:^|\\s)avg10=([0-9]+(?:\\.[0-9]+)?)", line)
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
        values: list[int] = []
        if resource is not None:
            try:
                soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
                if soft != resource.RLIM_INFINITY and int(soft) >= 0:
                    in_use = sum(
                        1 for _entry in Path("/proc/self/fd").iterdir()
                    )
                    values.append(max(0, int(soft) - in_use))
            except (OSError, ValueError):
                pass
        system = LocalHostRuntimeObserver._system_available_fds()
        if system is not None:
            values.append(system)
        return None if not values else min(values)

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

    def snapshot(self) -> HostRuntimeSnapshot:
        cpu = self._effective_cpu_cores()
        memory = self._effective_available_memory()
        try:
            load = float(os.getloadavg()[0])
        except (AttributeError, OSError):
            load = math.nan
        if cpu is None or memory is None or not math.isfinite(load) or load < 0:
            return HostRuntimeSnapshot(False, detail="local-host-runtime-facts-unavailable", observed_at_epoch_s=time())
        return HostRuntimeSnapshot(
            True,
            hosts=(HostRuntimeStatus(
                host_id=self._host_id,
                available=True,
                effective_cpu_cores=cpu,
                cpu_load_1m=load,
                available_memory_bytes=memory,
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
            observed_at_epoch_s=time(),
        )


__all__ = ["LocalHostRuntimeObserver"]
