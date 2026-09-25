"""Read-only host and operating-system facts for model qualification."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import re

from noetrium_platform.capabilities.model.qualification.api import HostExecutionFacts, OperatingSystemFacts


class HostFactsProbe:
    """Capture local host facts without mutating host state."""
    @staticmethod
    def operating_system() -> OperatingSystemFacts:
        values: dict[str, str] = {}
        path = Path("/etc/os-release")
        if path.is_file():
            for line in path.read_text("utf-8", errors="replace").splitlines():
                key, separator, value = line.partition("=")
                if separator:
                    values[key] = value.strip().strip('"')
        return OperatingSystemFacts(
            system=platform.system(),
            distribution=values.get("PRETTY_NAME", values.get("ID", "unknown")),
            distribution_version=values.get("VERSION_ID", "unknown"),
            kernel=platform.release(),
            machine=platform.machine(),
        )

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
        if not path.is_file():
            return None
        try:
            lines = path.read_text("utf-8", errors="replace").splitlines()
        except OSError:
            return None
        for line in lines:
            name, separator, raw = line.partition(":")
            if name != key or not separator:
                continue
            match = re.search(r"(\d+)", raw)
            if not match:
                return None
            return int(match.group(1)) * 1024
        return None

    def host(self, timeout: float) -> tuple[HostExecutionFacts, list[str]]:
        errors: list[str] = []
        logical = os.cpu_count() or 0
        if logical == 0:
            errors.append("logical CPU count unavailable")
        physical = self._meminfo_bytes("MemTotal")
        available = self._meminfo_bytes("MemAvailable")
        if physical is None:
            errors.append("physical memory total unavailable")
        if available is None:
            errors.append("available memory unavailable")

        libc, libc_version = platform.libc_ver()
        libc = libc or None
        libc_version = libc_version or None
        if libc is None:
            errors.append("libc identity unavailable")

        memory_limit = self._integer_file(Path("/sys/fs/cgroup/memory.max"))
        memory_current = self._integer_file(Path("/sys/fs/cgroup/memory.current"))
        if not Path("/sys/fs/cgroup/memory.max").is_file():
            errors.append("cgroup memory limit unavailable")
        pids_limit = self._integer_file(Path("/sys/fs/cgroup/pids.max"))
        if not Path("/sys/fs/cgroup/pids.max").is_file():
            errors.append("cgroup pids limit unavailable")

        nofile_soft: int | None = None
        nofile_hard: int | None = None
        try:
            import resource

            nofile_soft, nofile_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        except (ImportError, AttributeError, OSError):
            errors.append("nofile limits unavailable")

        container = os.environ.get("container")
        if not container:
            if Path("/.dockerenv").exists():
                container = "docker"
            elif Path("/run/.containerenv").exists():
                container = "podman"

        # ``timeout`` is retained in the signature so every host probe shares
        # one bounded operation budget; local facts themselves are read-only.
        _ = timeout
        return HostExecutionFacts(
            hostname=platform.node() or "unknown",
            cpu_architecture=platform.machine() or "unknown",
            logical_cpu_count=logical,
            physical_memory_bytes=physical,
            available_memory_bytes=available,
            libc=libc,
            libc_version=libc_version,
            cgroup_memory_limit_bytes=memory_limit,
            cgroup_memory_current_bytes=memory_current,
            nofile_soft=nofile_soft,
            nofile_hard=nofile_hard,
            pids_limit=pids_limit,
            container_runtime=container,
            errors=tuple(errors),
        ), errors


__all__ = ["HostFactsProbe"]
