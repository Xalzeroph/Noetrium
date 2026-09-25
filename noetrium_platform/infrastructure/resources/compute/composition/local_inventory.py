from __future__ import annotations

import math
import os
from pathlib import Path
import platform

from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE, ScopeIdentity
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeGPU,
    ComputeHost,
    ComputeInventoryPort,
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


def _merge_labels(
    current: tuple[tuple[str, str], ...],
    discovered: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    values = dict(current)
    values.update(dict(discovered))
    return tuple(sorted(values.items()))


def reconcile_local_compute_host(
    *,
    inventory: ComputeInventoryPort,
    gpu_runtime_observer: GpuRuntimeObserverPort,
    scope: ScopeIdentity = PLATFORM_SCOPE,
    host_id: str | None = None,
) -> ComputeHost:
    """Refresh physical host fingerprint while preserving operator policy.

    Discovery owns physical capacity, device identity and runtime-index facts.
    Inventory state owns scheduling policy, reservations and device health. The
    exact previous host value is used as the CAS generation, so a stale probe
    can never overwrite a newer operator or health-controller update.
    """

    discovered = discover_local_compute_host(
        gpu_runtime_observer=gpu_runtime_observer,
        scope=scope,
        host_id=host_id,
    )
    try:
        current = inventory.host(discovered.host_id)
    except KeyError:
        inventory.register_host(discovered)
        return discovered
    if current.scope != discovered.scope:
        raise ValueError("local compute fingerprint cannot change host scope")

    current_gpus = {gpu.gpu_id: gpu for gpu in current.gpus}
    refreshed_gpus: list[ComputeGPU] = []
    for gpu in discovered.gpus:
        previous = current_gpus.get(gpu.gpu_id)
        if previous is None:
            refreshed_gpus.append(gpu)
            continue
        refreshed_gpus.append(
            ComputeGPU(
                gpu_id=gpu.gpu_id,
                memory_bytes=gpu.memory_bytes,
                model=gpu.model,
                labels=_merge_labels(previous.labels, gpu.labels),
                health=previous.health,
                reserved_memory_bytes=previous.reserved_memory_bytes,
            )
        )

    replacement = ComputeHost(
        host_id=discovered.host_id,
        scope=discovered.scope,
        cpu_cores=discovered.cpu_cores,
        memory_bytes=discovered.memory_bytes,
        gpus=tuple(refreshed_gpus),
        labels=_merge_labels(current.labels, discovered.labels),
        enabled=current.enabled,
        scheduling_state=current.scheduling_state,
        reserved_cpu_cores=current.reserved_cpu_cores,
        reserved_memory_bytes=current.reserved_memory_bytes,
    )
    return inventory.replace_host(current, replacement)


__all__ = ["discover_local_compute_host", "reconcile_local_compute_host"]
