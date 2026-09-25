from __future__ import annotations

import math
import os
from pathlib import Path
import platform

from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE, ScopeIdentity
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeGPU,
    ComputeHost,
    GpuRuntimeObserverPort,
)


def _integer_file(path: Path) -> int | None:
    try:
        raw = path.read_text("utf-8", errors="replace").strip()
    except OSError:
        return None
    if raw in {"", "max"}:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _memtotal_bytes() -> int:
    try:
        rows = Path("/proc/meminfo").read_text(
            "utf-8", errors="replace"
        ).splitlines()
    except OSError as exc:
        raise RuntimeError("local compute memory inventory unavailable") from exc
    for row in rows:
        name, sep, raw = row.partition(":")
        if name != "MemTotal" or not sep:
            continue
        fields = raw.strip().split()
        if not fields:
            break
        return int(fields[0]) * 1024
    raise RuntimeError("local compute MemTotal unavailable")


def _effective_memory_capacity() -> int:
    total = _memtotal_bytes()
    cgroup_limit = _integer_file(Path("/sys/fs/cgroup/memory.max"))
    if cgroup_limit is not None and cgroup_limit > 0:
        total = min(total, cgroup_limit)
    if total <= 0:
        raise RuntimeError("local compute memory capacity must be positive")
    return total


def _effective_cpu_capacity() -> int:
    try:
        affinity = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        affinity = os.cpu_count() or 0
    if affinity <= 0:
        raise RuntimeError("local compute CPU inventory unavailable")
    effective = float(affinity)
    try:
        fields = Path("/sys/fs/cgroup/cpu.max").read_text(
            "utf-8", errors="replace"
        ).strip().split()
    except OSError:
        fields = []
    if len(fields) == 2 and fields[0] != "max":
        try:
            quota = int(fields[0])
            period = int(fields[1])
        except ValueError:
            quota = period = 0
        if quota > 0 and period > 0:
            effective = min(effective, quota / period)
    if not math.isfinite(effective) or effective <= 0:
        raise RuntimeError("local compute effective CPU capacity unavailable")
    return max(1, int(math.floor(effective)))


def discover_local_compute_host(
    *,
    gpu_runtime_observer: GpuRuntimeObserverPort,
    scope: ScopeIdentity = PLATFORM_SCOPE,
    host_id: str | None = None,
) -> ComputeHost:
    """Discover stable local capacity without downstream resource declarations.

    GPU UUID is the inventory identity because it remains stable across device
    index reorderings.  The current device index is retained only as a label so
    launch materializers can translate exact allocations to CUDA-visible
    indices when required.
    """

    resolved_host_id = (host_id or platform.node()).strip()
    if not resolved_host_id:
        raise RuntimeError("local compute host identity unavailable")
    snapshot = gpu_runtime_observer.snapshot()
    if not snapshot.available:
        raise RuntimeError(
            f"local GPU inventory unavailable: {snapshot.detail or 'unknown'}"
        )
    gpus = tuple(
        ComputeGPU(
            device.uuid,
            device.memory_total_mb * 1024 * 1024,
            device.name,
            (
                ("runtime_index", device.index),
                ("discovery", "nvidia-smi"),
            ),
        )
        for device in sorted(snapshot.devices, key=lambda row: row.index)
    )
    return ComputeHost(
        host_id=resolved_host_id,
        scope=scope,
        cpu_cores=_effective_cpu_capacity(),
        memory_bytes=_effective_memory_capacity(),
        gpus=gpus,
        labels=(
            ("discovery", "local-auto"),
            ("hostname", resolved_host_id),
        ),
    )


__all__ = ["discover_local_compute_host"]
