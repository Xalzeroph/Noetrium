from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.kernel.unit import NoetriumUnit

from .contracts import ComputeCluster, ComputeHost


class ComputeInventoryPort(Protocol):
    def register_host(self, host: ComputeHost) -> None: ...
    def host(self, host_id: str) -> ComputeHost: ...
    def list_hosts(
        self,
        *,
        scope: NoetriumUnit | None = None,
    ) -> tuple[ComputeHost, ...]: ...
    def register_cluster(self, cluster: ComputeCluster) -> None: ...
    def cluster(self, cluster_id: str) -> ComputeCluster: ...


__all__ = ["ComputeInventoryPort"]
