from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.governance.api import ScopeIdentity

from .contracts import ComputeAllocation, ComputeBindingProof, ComputeCluster, ComputeHost, ComputeLeasePolicy, ComputeRequirement


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
    def create(self, allocations: tuple[ComputeAllocation, ...]) -> ComputeLeaseGuardPort: ...

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
        excluded_gpus: frozenset[tuple[str, str]] = frozenset(),
    ) -> ComputeAllocation: ...
    def unbound_placement_satisfies(
        self,
        allocation: ComputeAllocation,
        requirement: ComputeRequirement,
    ) -> bool:
        """Revalidate one exact unbound placement against current physical facts."""
        ...
    def renew_many(
        self, allocations: tuple[ComputeAllocation, ...], *, ttl_seconds: float, now: float | None = None
    ) -> tuple[ComputeAllocation, ...]: ...
    def retain_many(
        self, allocations: tuple[ComputeAllocation, ...], *, now: float | None = None
    ) -> tuple[ComputeAllocation, ...]: ...
    def confirm_bound(
        self,
        proof: ComputeBindingProof,
    ) -> ComputeAllocation: ...
    def replace_bound(
        self,
        proof: ComputeBindingProof,
        *,
        previous_binding_proof_digest: str,
    ) -> ComputeAllocation: ...
    def reacquire(
        self,
        allocation: ComputeAllocation,
        *,
        ttl_seconds: float,
        now: float | None = None,
    ) -> ComputeAllocation:
        """Reacquire one exact durable allocation with fresh fencing."""
        ...
    def reconcile_expired(
        self, *, now: float | None = None
    ) -> tuple[ComputeAllocation, ...]: ...
    def release(self, allocation: ComputeAllocation) -> None:
        """Exact live-owner retirement after its upper process/container converged."""
        ...
    def recover_release(self, allocation: ComputeAllocation) -> None:
        """Exclusive recovery/shutdown retirement after upper physical convergence."""
        ...
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
