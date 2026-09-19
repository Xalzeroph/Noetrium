from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.scope.api import ScopeIdentity

from .contracts import ComputeAllocation, ComputeCluster, ComputeHost, ComputeLeasePolicy, ComputeRequirement


class ComputeInventoryPort(Protocol):
    def register_host(self, host: ComputeHost) -> None: ...
    def host(self, host_id: str) -> ComputeHost: ...
    def list_hosts(self, *, scope: ScopeIdentity | None = None) -> tuple[ComputeHost, ...]: ...
    def register_cluster(self, cluster: ComputeCluster) -> None: ...
    def cluster(self, cluster_id: str) -> ComputeCluster: ...


class ComputeCandidatePort(Protocol):
    """Read-only capacity projection for preflight and planning consumers."""

    def candidates(
        self,
        requirement: ComputeRequirement,
        *,
        scope: ScopeIdentity | None = None,
    ) -> tuple[ComputeHost, ...]: ...




class ComputeLeaseGuardPort(Protocol):
    def start(self) -> None: ...
    def assert_healthy(self) -> None: ...
    def close(self) -> None: ...


class ComputeLeaseGuardFactoryPort(Protocol):
    @property
    def policy(self) -> ComputeLeasePolicy: ...
    def create(self, allocation_ids: tuple[str, ...]) -> ComputeLeaseGuardPort: ...

class ComputeSchedulerPort(ComputeCandidatePort, Protocol):
    def allocate(
        self,
        allocation_id: str,
        scope: ScopeIdentity,
        requirement: ComputeRequirement,
        *,
        placement_scope: ScopeIdentity | None = None,
        ttl_seconds: float | None = None,
        now: float | None = None,
    ) -> ComputeAllocation: ...
    def renew_many(
        self, allocation_ids: tuple[str, ...], *, ttl_seconds: float, now: float | None = None
    ) -> tuple[ComputeAllocation, ...]: ...
    def reconcile_expired(
        self, *, now: float | None = None
    ) -> tuple[ComputeAllocation, ...]: ...
    def release(self, allocation_id: str) -> None: ...
    def allocations(
        self,
        *,
        scope: ScopeIdentity | None = None,
    ) -> tuple[ComputeAllocation, ...]: ...


__all__ = [
    "ComputeCandidatePort",
    "ComputeInventoryPort",
    "ComputeLeaseGuardFactoryPort",
    "ComputeLeaseGuardPort",
    "ComputeSchedulerPort",
]
