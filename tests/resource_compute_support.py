from __future__ import annotations

from pathlib import Path
from tempfile import mkdtemp
from typing import Any

from noetrium_platform.foundation.governance.api import ScopeIdentity
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeCluster,
    ComputeGPU,
    ComputeHost,
    GpuDeviceStatus,
    GpuRuntimeSnapshot,
)
from noetrium_platform.infrastructure.resources.compute.runtime import ComputeScheduler
from noetrium_platform.infrastructure.resources.lease.runtime import ManualLeaseClock


class TestComputeInventory:
    """Test-only ComputeInventoryPort fake for deterministic fault injection."""

    __test__ = False

    def __init__(self) -> None:
        self._hosts: dict[str, ComputeHost] = {}
        self._clusters: dict[str, ComputeCluster] = {}

    def register_host(self, host: ComputeHost) -> None:
        prior = self._hosts.get(host.host_id)
        if prior is not None and prior != host:
            raise ValueError(f"host identity already registered: {host.host_id}")
        self._hosts[host.host_id] = host

    def host(self, host_id: str) -> ComputeHost:
        try:
            return self._hosts[host_id]
        except KeyError as exc:
            raise KeyError(host_id) from exc

    def list_hosts(self, *, scope: ScopeIdentity | None = None) -> tuple[ComputeHost, ...]:
        return tuple(
            sorted(
                (
                    host
                    for host in self._hosts.values()
                    if scope is None or host.scope == scope
                ),
                key=lambda host: host.host_id,
            )
        )

    def register_cluster(self, cluster: ComputeCluster) -> None:
        missing = [host_id for host_id in cluster.host_ids if host_id not in self._hosts]
        if missing:
            raise KeyError(missing[0])
        prior = self._clusters.get(cluster.cluster_id)
        if prior is not None and prior != cluster:
            raise ValueError(f"cluster identity already registered: {cluster.cluster_id}")
        self._clusters[cluster.cluster_id] = cluster

    def cluster(self, cluster_id: str) -> ComputeCluster:
        try:
            return self._clusters[cluster_id]
        except KeyError as exc:
            raise KeyError(cluster_id) from exc


class IdleGpuRuntimeObserver:
    def __init__(self, *gpu_ids: str) -> None:
        self._gpu_ids = tuple(gpu_ids)

    def snapshot(self) -> GpuRuntimeSnapshot:
        return GpuRuntimeSnapshot(
            True,
            devices=tuple(
                GpuDeviceStatus(
                    gpu_id,
                    gpu_id,
                    "test-gpu",
                    1024 * 1024,
                    0,
                    1024 * 1024,
                    0,
                )
                for gpu_id in self._gpu_ids
            ),
            processes=(),
            processes_complete=True,
        )


def idle_gpu_runtime_observer(*gpu_ids: str) -> IdleGpuRuntimeObserver:
    return IdleGpuRuntimeObserver(*gpu_ids)


def compute_scheduler(
    inventory: TestComputeInventory,
    *,
    state_path: str | Path | None = None,
    clock: ManualLeaseClock | None = None,
    **kwargs: Any,
) -> ComputeScheduler:
    """Bind the sole production ComputeScheduler to a test inventory port."""

    path = Path(state_path) if state_path is not None else Path(mkdtemp(prefix="noetrium-compute-test-")) / "compute.sqlite"
    return ComputeScheduler(
        path,
        inventory,
        clock=clock
        or ManualLeaseClock(
            elapsed_seconds=1.0,
            wall_epoch_seconds=100.0,
        ),
        **kwargs,
    )


__all__ = [
    "IdleGpuRuntimeObserver",
    "TestComputeInventory",
    "compute_scheduler",
    "idle_gpu_runtime_observer",
]
