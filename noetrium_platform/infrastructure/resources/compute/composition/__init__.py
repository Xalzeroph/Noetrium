from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeHost,
    GpuRuntimeObserverPort,
    HostRuntimeObserverPort,
)
from noetrium_platform.infrastructure.resources.compute.runtime import (
    ComputeInventory,
    ComputeScheduler,
)
from noetrium_platform.infrastructure.resources.lease.api import LeaseClockPort

from .local_inventory import discover_local_compute_host


@dataclass(frozen=True, slots=True)
class ComputeAuthorityStack:
    """The single durable compute authority composition."""

    inventory: ComputeInventory
    scheduler: ComputeScheduler


def compose_compute_authority(
    state_path: str | Path,
    hosts: Iterable[ComputeHost] = (),
    *,
    clock: LeaseClockPort,
    gpu_runtime_observer: GpuRuntimeObserverPort | None = None,
    host_runtime_observer: HostRuntimeObserverPort | None = None,
) -> ComputeAuthorityStack:
    """Compose the one restart-safe compute inventory and scheduler authority."""

    inventory = ComputeInventory(state_path)
    for host in hosts:
        inventory.register_host(host)
    scheduler = ComputeScheduler(
        state_path,
        inventory,
        clock=clock,
        gpu_runtime_observer=gpu_runtime_observer,
        host_runtime_observer=host_runtime_observer,
    )
    return ComputeAuthorityStack(inventory, scheduler)


__all__ = [
    "ComputeAuthorityStack",
    "compose_compute_authority",
    "discover_local_compute_host",
]
