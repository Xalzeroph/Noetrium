from __future__ import annotations

from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeCluster,
    ComputeGPU,
    ComputeHost,
    GpuDeviceStatus,
    GpuRuntimeSnapshot,
)


class TestComputeInventory:
    """Deterministic test-only ComputeInventoryPort; no lifecycle authority."""

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
        return self._hosts[host_id]

    def list_hosts(self, *, scope: NoetriumUnit | None = None) -> tuple[ComputeHost, ...]:
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
        missing = [row for row in cluster.host_ids if row not in self._hosts]
        if missing:
            raise KeyError(missing[0])
        prior = self._clusters.get(cluster.cluster_id)
        if prior is not None and prior != cluster:
            raise ValueError(f"cluster identity already registered: {cluster.cluster_id}")
        self._clusters[cluster.cluster_id] = cluster

    def cluster(self, cluster_id: str) -> ComputeCluster:
        return self._clusters[cluster_id]


class IdleGpuRuntimeObserver:
    def __init__(self, *gpu_ids: str) -> None:
        self._gpu_ids = tuple(gpu_ids)

    def snapshot(self) -> GpuRuntimeSnapshot:
        return GpuRuntimeSnapshot(
            True,
            devices=tuple(
                GpuDeviceStatus(
                    str(index),
                    gpu_id,
                    "test-gpu",
                    1024 * 1024,
                    0,
                    1024 * 1024,
                    0,
                )
                for index, gpu_id in enumerate(self._gpu_ids)
            ),
            processes=(),
            processes_complete=True,
        )


def idle_gpu_runtime_observer(*gpu_ids: str) -> IdleGpuRuntimeObserver:
    return IdleGpuRuntimeObserver(*gpu_ids)


__all__ = [
    "IdleGpuRuntimeObserver",
    "TestComputeInventory",
    "idle_gpu_runtime_observer",
]
