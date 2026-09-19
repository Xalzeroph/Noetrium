from __future__ import annotations

import math
import os
from pathlib import Path
import platform
import re

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
            return HostRuntimeSnapshot(False, detail="local-host-runtime-facts-unavailable")
        return HostRuntimeSnapshot(
            True,
            hosts=(HostRuntimeStatus(
                host_id=self._host_id,
                available=True,
                effective_cpu_cores=cpu,
                cpu_load_1m=load,
                available_memory_bytes=memory,
            ),),
        )


__all__ = ["LocalHostRuntimeObserver"]
